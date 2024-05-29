from prefect import task

from strom.prefect_ops import task_ops

import duckdb
import pandas as pd

from datetime import datetime, timedelta

strom_prices = {"normalstrom_minute": 0.3713, "waermestrom_minute": 0.2763}
meterid = {"normalstrom_minute": "(1)", "waermestrom_minute": "(2, 3)"}


def calculate_avg_consumption_periods(
    periods=None,
    minute_table="normalstrom_minute",
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

    price = strom_prices.get(minute_table)

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


def calculate_avg_consumption(
    begin=None,
    fin=None,
    minute_table="normalstrom_minute",
    duckdb_file="./duckdb/strom.duckdb",
):

    if begin is None:
        with duckdb.connect(duckdb_file) as con:
            begin = con.sql(f"SELECT MIN(minute) FROM strom_minute").fetchone()[0]

    if fin is None:
        with duckdb.connect(duckdb_file) as con:
            fin = con.sql(f"SELECT MAX(minute) FROM strom_minute").fetchone()[0]

    price = strom_prices.get(minute_table)

    with duckdb.connect(duckdb_file) as con:
        strom_avg = con.sql(
            f"""
            SELECT 
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
            FROM strom_minute
            WHERE minute >= '{begin}' AND minute <= '{fin}' AND
            meterid IN {meterid.get(minute_table)}
            ;
            """
        ).df()
    return strom_avg


def get_period_cummulative(
    begin=None,
    fin=None,
    duckdb_file="./duckdb/strom.duckdb",
):
    if begin is None:
        with duckdb.connect(duckdb_file) as con:
            begin = con.sql(f"SELECT MIN(date) FROM strom_per_day").fetchone()[0]

    if fin is None:
        with duckdb.connect(duckdb_file) as con:
            fin = con.sql(f"SELECT MAX(date) FROM strom_per_day").fetchone()[0]

    with duckdb.connect(duckdb_file) as con:
        period = con.sql(
            f"""
            SELECT 
                *,
                SUM(nd) OVER (ORDER BY date) AS nd_cum,
                SUM(wd) OVER (ORDER BY date) AS wd_cum
            FROM strom_per_day
            WHERE date >= '{begin}' AND date <= '{fin}'
            ORDER BY date
            ;
            """
        ).df()

    return period


def get_period(
    begin=None,
    fin=None,
    minute_table="normalstrom_minute",
    duckdb_file="./duckdb/strom.duckdb",
):

    daily = get_period_cummulative(begin, fin, duckdb_file)

    average = calculate_avg_consumption(begin, fin, minute_table, duckdb_file)

    return daily, average


@task(**task_ops)
def compare_last_days(
    days=15,
    years_back=4,
    duckdb_file="./duckdb/strom.duckdb",
):

    with duckdb.connect(duckdb_file) as con:
        fin = con.sql(f"SELECT MAX(date) FROM strom_per_day").fetchone()[0]

    begin = fin - timedelta(days=days)

    # we only want to return the average details for the requested period
    # and not for the other periods to compare to
    average = {
        "normalstrom": calculate_avg_consumption(
            begin, fin, "normalstrom_minute", duckdb_file
        ),
        "waermestrom": calculate_avg_consumption(
            begin, fin, "waermestrom_minute", duckdb_file
        ),
    }

    daily = dict()
    daily[fin.year] = get_period_cummulative(begin, fin, duckdb_file)

    for i in range(1, years_back):
        fin = fin - timedelta(days=365.25)
        begin = begin - timedelta(days=365.25)
        daily[fin.year] = get_period_cummulative(begin, fin, duckdb_file)

    daily = pd.concat(
        [df.assign(year=key) for key, df in daily.items()], ignore_index=True
    )

    return daily, average


@task(**task_ops)
def normalstrom_consumption(duckdb_file, normalstrom_minute, *args, **kwargs):
    return calculate_avg_consumption(
        minute_table="normalstrom_minute",
        duckdb_file=duckdb_file,
    )


@task(**task_ops)
def waermestrom_consumption(duckdb_file, waermestrom_minute, *args, **kwargs):
    return calculate_avg_consumption(
        minute_table="waermestrom_minute",
        duckdb_file=duckdb_file,
    )
