from prefect import task

from strom.prefect_ops import task_ops

import duckdb
import pandas as pd


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
            "SELECT md5(string_agg(normalstrom::text, '')) AS md5 FROM normalstrom;"
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
def make_strom_per_day(
    normalstrom_minute, waermestrom_minute, duckdb_file="./duckdb/strom.duckdb"
):
    with duckdb.connect(duckdb_file) as con:
        waermestrom_per_day = con.sql(
            f"""
            CREATE OR REPLACE TABLE waermestrom_per_day AS
            SELECT 
                minute::DATE AS date,
                24.0 * 60.0 * AVG(cm) AS wd,
                SUM(CASE WHEN value IS NOT NULL THEN 1 ELSE 0 END) AS wobs,
            FROM waermestrom_minute
            GROUP BY minute::DATE
            ;
            SELECT * FROM waermestrom_per_day;
            """
        ).df()
        normalstrom_per_day = con.sql(
            f"""
            CREATE OR REPLACE TABLE normalstrom_per_day AS
            SELECT 
                minute::DATE AS date,
                24.0 * 60.0 * AVG(cm) AS nd,
                SUM(CASE WHEN value IS NOT NULL THEN 1 ELSE 0 END) AS nobs,
            FROM normalstrom_minute
            GROUP BY minute::DATE
            ;
            SELECT * FROM normalstrom_per_day;
            """
        ).df()
        strom_per_day = con.sql(
            f"""
            CREATE OR REPLACE TABLE strom_per_day AS
            SELECT 
                normalstrom_per_day.date AS date,
                normalstrom_per_day.nobs AS obs,
                normalstrom_per_day.nd AS nd,
                waermestrom_per_day.wd AS wd
            FROM normalstrom_per_day
            INNER JOIN waermestrom_per_day 
            ON normalstrom_per_day.date = waermestrom_per_day.date
            ;
            SELECT * FROM strom_per_day;
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
