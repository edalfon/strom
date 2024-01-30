from prefect import flow, task

from prefect.tasks import task_input_hash
from prefect.filesystems import LocalFileSystem

from strom import dwd

import pandas as pd
import numpy as np

from datetime import date

import epyfun
import duckdb

import json
from prefect.results import PersistedResultBlob
from prefect.serializers import PickleSerializer, JSONSerializer

task_ops = dict(
    cache_key_fn=task_input_hash,
    result_storage_key="{task_run.task_name}",
    result_storage=LocalFileSystem(basepath=".prefect/"),
    refresh_cache=None,
    persist_result=True,
)


def read_result(
    filename: str, storage=task_ops["result_storage"], serialier: str = "pickle"
):
    path = storage._resolve_path(filename)
    with open(path, "rb") as buffered_reader:
        dict_obj = json.load(buffered_reader)
        blob = PersistedResultBlob.parse_obj(dict_obj)
    if serialier == "json":
        result = JSONSerializer().loads(blob.data)
    else:
        result = PickleSerializer().loads(blob.data)
    return result


def calculate_avg_consumption(
    periods=None,
    minute_table="normalstrom_minute",
    price=0.3894,
    duckdb_file="./duckdb/strom.duckdb",
):
    if periods is None:
        with duckdb.connect(duckdb_file) as con:
            periods = con.sql(
                f"""
                SELECT 'All' AS name, MIN(date) AS begin, MAX(date) AS fin 
                FROM {minute_table}
                """
            ).df()
    periods = pd.DataFrame(periods)
    with duckdb.connect(duckdb_file) as con:
        con.sql("DROP TABLE IF EXISTS periods;")
        strom_avg = con.sql(
            f"""
            SELECT 
                p.name,
                p.begin,
                p.fin,
                MIN(value) AS Min,
                MAX(value) AS Max,
                MAX(value) - MIN(value) AS Use2,
                SUM(cm) AS Use,

                MIN(date) AS First,
                MAX(date) AS Last,
                date_sub('minute', MIN(minute), MAX(minute)) AS Mins, 

                24.0 * 60.0 * Use / Mins AS "Use/Day",
                365.25 * "Use/Day" AS "Use/Year",
                {price} * "Use/Day" AS "Daily Exp",
                {price} * "Use/Year" AS "Yearly Exp"
            FROM periods p
            JOIN {minute_table} d
            ON d.minute BETWEEN p.begin AND p.fin
            GROUP BY p.name, p.begin, p.fin
            ;
            """
        ).df()
    return strom_avg


@task(**task_ops)
def ingest_normalstrom(sqlite_file, duckdb_file="./duckdb/strom.duckdb"):
    with duckdb.connect(duckdb_file) as con:
        # con.sql("INSTALL sqlite;")
        # con.sql("LOAD sqlite;")
        con.install_extension("sqlite")
        con.load_extension("sqlite")
        con.sql(
            f"""
            CREATE OR REPLACE TABLE normalstrom AS 
            WITH strom_sqlite AS (
                SELECT 
                    meterid, 
                    -- Blob Functions, because most columns get read as blob
                    -- https://duckdb.org/docs/sql/functions/blob
                    decode(date)::DATETIME AS date, 
                    decode(value)::INT AS value
                FROM sqlite_scan('{sqlite_file}', 'reading') 
                WHERE meterid = 1
            )
            SELECT *,
            -- add default values to lag(), to prevent null in the first row
            date_sub('minute', lag(date, 1, '2020-11-30 00:00:00') over(order by date), date) AS minutes, 
            -- add default values to lag(), to prevent null in the first row
            value - lag(value, 1, 12160) over(order by date) AS consumption,
            1.0 * consumption / minutes AS cm,
            24.0 * 60.0 * consumption / minutes AS consumption_day_equivalent
            FROM strom_sqlite
            ORDER BY date
            ;
            """
        )
        return con.sql(
            "SELECT md5(string_agg(normalstrom::text, '')) FROM normalstrom;"
        ).df()
        # return con.sql("SELECT * FROM normalstrom;").df()
    # TODO: see what to return, after checking god practices for DB+Prefect


@task(**task_ops)
def expand_normalstrom_minute(normalstrom, duckdb_file="./duckdb/strom.duckdb"):
    with duckdb.connect(duckdb_file) as con:
        con.sql(
            f"""
            CREATE OR REPLACE TABLE normalstrom_minute_nulls AS
            WITH minutes_table AS (
                SELECT UNNEST(generate_series(ts[1], ts[2], interval 1 minute)) as minute
                FROM (VALUES (
                [(SELECT MIN(date) FROM normalstrom), (SELECT MAX(DATE) FROM normalstrom)]
                )) t(ts)
            )
            SELECT * 
            FROM minutes_table
            LEFT JOIN normalstrom
            ON minutes_table.minute = normalstrom.date
            ;

            CREATE OR REPLACE TABLE normalstrom_minute AS
            SELECT
                minute,
                date,
                value,
                minutes,
                consumption,
                FIRST_VALUE(cm IGNORE NULLS) OVER(
                ORDER BY minute ROWS BETWEEN CURRENT ROW AND UNBOUNDED FOLLOWING 
                ) AS cm
            FROM normalstrom_minute_nulls t1
            ORDER BY t1.minute
            ;
            """
        )
        return con.sql(
            "SELECT md5(string_agg(normalstrom_minute::text, '')) FROM normalstrom_minute;"
        ).df()
        # return con.sql("SELECT * FROM normalstrom_minute;").df()


@task(**task_ops)
def ingest_waermestrom(sqlite_file, duckdb_file="./duckdb/strom.duckdb"):
    with duckdb.connect(duckdb_file) as con:
        con.sql(
            f"""
            CREATE OR REPLACE TABLE waermestrom_nulls AS
            WITH
            ws181 AS (
            SELECT 
                'Hoch' AS tariff,
                decode(date)::DATETIME AS date, 
                decode(value)::INT AS value
            FROM sqlite_scan('{sqlite_file}', 'reading') 
            WHERE meterid = 3 
            ),
            ws182 AS (
            SELECT 
                'Niedrig' AS tariff, 
                decode(date)::DATETIME AS date, 
                decode(value)::INT AS value
            FROM sqlite_scan('{sqlite_file}', 'reading') 
            WHERE meterid = 2
            )
            SELECT
            COALESCE(ws181.date, ws182.date) AS date,
            ws181.value AS value_hoch,
            ws182.value AS value_niedrig
            FROM ws181 
            FULL JOIN ws182 
            ON ws181.date = ws182.date
            ORDER BY date
            ;

            CREATE OR REPLACE TABLE waermestrom_nonulls AS
            SELECT
            date,
            value_hoch, value_niedrig, 
            -- calculate minutes diff with previous and next date, to see which is closer
            -- note the use of a default value for lag/lead, substracting and adding one day
            -- for lag and lead respectively, to avoid NULLs in the first and las rows
            date_sub('minute', lag(date, 1, date - INTERVAL 1 DAY) over(order by date), date) AS minutes_lag,
            date_sub('minute', date, lead(date, 1, date + INTERVAL 1 DAY) over(order by date)) AS minutes_lead,
            -- and we want to replace null values column, with the value from closest date
            CASE
                WHEN value_hoch IS NULL AND minutes_lag <= minutes_lead 
                THEN lag(value_hoch) over(order by date)
                WHEN value_hoch IS NULL AND minutes_lag > minutes_lead 
                THEN lead(value_hoch) over(order by date)
                ELSE value_hoch
            END AS value_hoch_fix,
            CASE
                WHEN value_niedrig IS NULL AND minutes_lag <= minutes_lead 
                THEN lag(value_niedrig) over(order by date)
                WHEN value_niedrig IS NULL AND minutes_lag > minutes_lead 
                THEN lead(value_niedrig) over(order by date)
                ELSE value_niedrig
            END AS value_niedrig_fix,
            value_hoch_fix + value_niedrig_fix AS value
            FROM waermestrom_nulls 
            ORDER BY date
            ;

            CREATE OR REPLACE TABLE waermestrom AS
            SELECT 
            date,
            value,
            value_hoch_fix AS value_hoch,
            value_niedrig_fix AS value_niedrig,
            minutes_lag AS minutes,
            -- add default values to lag(), to prevent null in the first row
            -- use 11kwh less than the first value which is approximately the avg consumption per day
            -- and would be equivalent to the minutes in the first row, that we set with the default
            -- of one day in the previous query 
            value - lag(value, 1, value-11) over(order by date) AS consumption,
            1.0 * consumption / minutes_lag AS cm,
            24.0 * 60.0 * consumption / minutes_lag AS consumption_day_equivalent,
            -- now calculate consumption per tariff
            value_hoch_fix - lag(value_hoch_fix, 1, value_hoch_fix-11) over(order by date) AS consumption_hoch,
            value_niedrig_fix - lag(value_niedrig_fix, 1, value_niedrig_fix-11) over(order by date) AS consumption_niedrig,
            1.0 * consumption_hoch / minutes_lag AS cm_hoch,
            1.0 * consumption_niedrig / minutes_lag AS cm_niedrig
            FROM waermestrom_nonulls 
            WHERE minutes > 1 --get rid of the artificially short periods
            ;

            """
        )
        return con.sql(
            "SELECT md5(string_agg(waermestrom::text, '')) FROM waermestrom;"
        ).df()
        # return con.sql("SELECT * FROM waermestrom;").df()


@task(**task_ops)
def expand_waermestrom_minute(waermestrom, duckdb_file="./duckdb/strom.duckdb"):
    with duckdb.connect(duckdb_file) as con:
        con.sql(
            f"""
CREATE OR REPLACE TABLE waermestrom_minute_nulls AS
WITH minutes_table AS (
SELECT UNNEST(generate_series(ts[1], ts[2], interval 1 minute)) as minute
FROM (VALUES (
[(SELECT MIN(date) FROM waermestrom), (SELECT MAX(DATE) FROM waermestrom)]
)) t(ts)
)
SELECT * 
FROM minutes_table
LEFT JOIN waermestrom
ON minutes_table.minute = waermestrom.date
;

CREATE OR REPLACE TABLE waermestrom_minute AS
SELECT
minute,
date,
value,
value_hoch,
value_niedrig,
minutes,
consumption,
FIRST_VALUE(cm IGNORE NULLS) OVER(
ORDER BY minute ROWS BETWEEN CURRENT ROW AND UNBOUNDED FOLLOWING 
) AS cm,
FIRST_VALUE(cm_hoch IGNORE NULLS) OVER(
ORDER BY minute ROWS BETWEEN CURRENT ROW AND UNBOUNDED FOLLOWING 
) AS cm_hoch,
FIRST_VALUE(cm_niedrig IGNORE NULLS) OVER(
ORDER BY minute ROWS BETWEEN CURRENT ROW AND UNBOUNDED FOLLOWING 
) AS cm_niedrig
FROM waermestrom_minute_nulls t1
ORDER BY t1.minute
;
            """
        )
        return con.sql(
            "SELECT md5(string_agg(waermestrom_minute::text, '')) FROM waermestrom_minute;"
        ).df()
        # return con.sql("SELECT * FROM waermestrom_minute;").df()


@task(**task_ops)
def get_climate_data(current_date):
    historical_files = dwd.download_climate_data(
        "https://opendata.dwd.de/climate_environment/CDC/observations_germany/climate/hourly/air_temperature/historical/"
    )
    recent_files = dwd.download_climate_data(
        "https://opendata.dwd.de/climate_environment/CDC/observations_germany/climate/hourly/air_temperature/recent/"
    )
    air = dwd.bind_rows_files(historical_files + recent_files)
    aircols = ["TT_TU", "RF_TU"]
    air.replace(-999, np.nan, inplace=True)

    historical_files = dwd.download_climate_data(
        "https://opendata.dwd.de/climate_environment/CDC/observations_germany/climate/hourly/dew_point/historical/"
    )
    recent_files = dwd.download_climate_data(
        "https://opendata.dwd.de/climate_environment/CDC/observations_germany/climate/hourly/dew_point/recent/"
    )
    dew = dwd.bind_rows_files(historical_files + recent_files)
    dewcols = ["  TT", "  TD"]
    dew.replace(-999, np.nan, inplace=True)

    historical_files = dwd.download_climate_data(
        "https://opendata.dwd.de/climate_environment/CDC/observations_germany/climate/hourly/moisture/historical/"
    )
    recent_files = dwd.download_climate_data(
        "https://opendata.dwd.de/climate_environment/CDC/observations_germany/climate/hourly/moisture/recent/"
    )
    moist = dwd.bind_rows_files(historical_files + recent_files)
    moistcols = ["VP_STD", "TF_STD", "P_STD", "TT_STD", "RF_STD", "TD_STD"]

    historical_files = dwd.download_climate_data(
        "https://opendata.dwd.de/climate_environment/CDC/observations_germany/climate/hourly/precipitation/historical/"
    )
    recent_files = dwd.download_climate_data(
        "https://opendata.dwd.de/climate_environment/CDC/observations_germany/climate/hourly/precipitation/recent/"
    )
    precip = dwd.bind_rows_files(historical_files + recent_files)
    precipcols = ["  R1", "RS_IND", "WRTR"]
    precip.replace(-999, np.nan, inplace=True)

    oncols = ["MESS_DATUM", "STATIONS_ID"]
    agg_df = air.merge(dew[oncols + dewcols], on=oncols)
    agg_df = agg_df.merge(moist[oncols + moistcols], on=oncols)
    agg_df = agg_df.merge(precip[oncols + precipcols], on=oncols)
    datacols = aircols + dewcols + moistcols + precipcols
    agg_df["date"] = agg_df["MESS_DATUM"].dt.normalize()
    agg_df = (
        agg_df.groupby("date")
        .agg({key: ["min", "mean", "max"] for key in datacols})
        .reset_index()
    )
    climate_daily = epyfun.pandas.clean_names(agg_df)

    return climate_daily


@task(**task_ops)
def make_strom_per_day(
    normalstrom_minute, waermestrom_minute, duckdb_file="./duckdb/strom.duckdb"
):
    with duckdb.connect(duckdb_file) as con:
        waermestrom_per_day = con.sql(
            f"""
            SELECT 
                minute::DATE AS date,
                24.0 * 60.0 * AVG(cm) AS wd,
                SUM(CASE WHEN value IS NOT NULL THEN 1 ELSE 0 END) AS wobs,
            FROM waermestrom_minute
            WHERE minute <= '2021-05-25' OR minute >= '2022-11-30'
            GROUP BY minute::DATE
            ;
            """
        ).df()
        normalstrom_per_day = con.sql(
            f"""
            SELECT 
                minute::DATE AS date,
                24.0 * 60.0 * AVG(cm) AS nd,
                SUM(CASE WHEN value IS NOT NULL THEN 1 ELSE 0 END) AS nobs,
            FROM normalstrom_minute
            WHERE minute <= '2021-05-25' OR minute >= '2022-11-30'
            GROUP BY minute::DATE
            ;
            """
        ).df()
        strom_per_day = pd.merge(
            normalstrom_per_day,
            waermestrom_per_day,
            on="date",
            validate="one_to_one",
        )
        strom_per_day = strom_per_day.drop(columns="nobs").rename(
            columns={"wobs": "obs"}
        )

        return strom_per_day


@task(**task_ops)
def merge_strom_climate_data(strom_per_day, climate_daily):
    strom_climate = pd.merge(strom_per_day, climate_daily, on="date", how="left")
    return strom_climate


@task(**task_ops)
def normalstrom_consumption(*args, **kwargs):
    return calculate_avg_consumption(**kwargs)


@task(**task_ops)
def waermestrom_consumption(*args, **kwargs):
    return calculate_avg_consumption(**kwargs)


def quarto_report(*args, **kwargs):
    import subprocess
    import os
    import webbrowser

    # subprocess.run("quarto render .\dashboard\customer-churn-dashboard\dashboard.qmd")
    subprocess.run("quarto render quarto --execute-dir .")
    # os.startfile(".\\results\\index.html", "open")

    webbrowser.open(".\\results\\index.html")


@flow(log_prints=True)
def strom_flow():
    """
    Given a GitHub repository, logs the number of stargazers
    and contributors for that repo.
    """

    duckdb_file = "./duckdb/strom.duckdb"
    epyfun.create_dir(duckdb_file)
    sqlite_file = epyfun.get_latest_file("./data/")

    normalstrom = ingest_normalstrom(sqlite_file, duckdb_file)
    normalstrom_minute = expand_normalstrom_minute(normalstrom, duckdb_file)

    waermestrom = ingest_waermestrom(sqlite_file, duckdb_file)
    waermestrom_minute = expand_waermestrom_minute(waermestrom, duckdb_file)

    strom_per_day = make_strom_per_day(
        normalstrom_minute, waermestrom_minute, duckdb_file
    )
    climate_daily = get_climate_data(date.today())
    strom_climate = merge_strom_climate_data(strom_per_day, climate_daily)

    normalstrom_consumption(
        normalstrom_minute,
        minute_table="normalstrom_minute",
        price=0.3713,
        duckdb_file=duckdb_file,
    )

    waermestrom_consumption(
        waermestrom_minute,
        minute_table="waermestrom_minute",
        price=0.2763,
        duckdb_file=duckdb_file,
    )

    quarto_report(strom_climate)


@task(**task_ops)
def foo():
    return "foo"


if __name__ == "__main__":
    strom_flow()
