from datetime import timedelta

import pandas as pd
from stepit import stepit

import duckdb

strom_prices = {"normalstrom_minute": 0.3713, "waermestrom_minute": 0.2763}
meterid = {"normalstrom_minute": "(1)", "waermestrom_minute": "(2, 3)"}


def calculate_avg_consumption_periods(
    periods=None,
    minute_table="normalstrom_minute",
    duckdb_file="./duckdb/strom.duckdb",
):
    m_id = meterid.get(minute_table)
    if periods is None:
        with duckdb.connect(duckdb_file) as con:
            periods = con.sql(
                f"""
                SELECT 'All' AS name, MIN(start_time) AS begin, MAX(end_time) AS fin 
                FROM strom_intervals
                WHERE meterid IN {m_id}
                """
            ).df()
    periods = pd.DataFrame(periods)

    price = strom_prices.get(minute_table)

    with duckdb.connect(duckdb_file) as con:
        con.sql("DROP TABLE IF EXISTS periods;")
        strom_avg = con.sql(
            f"""
            WITH interval_overlaps AS (
                SELECT 
                    p.name,
                    p.begin,
                    p.fin,
                    d.value,
                    d.end_time,
                    d.start_time,
                    cm * date_diff('minute', greatest(d.start_time, p.begin), least(d.end_time, p.fin)) AS overlap_use,
                    greatest(d.start_time, p.begin) AS eff_start,
                    least(d.end_time, p.fin) AS eff_end
                FROM periods p
                JOIN strom_intervals d ON d.start_time < p.fin AND d.end_time > p.begin
                WHERE d.meterid IN {m_id}
            ),
            agg AS (
                SELECT 
                    name, begin, fin,
                    MIN(value) AS Min,
                    MAX(value) AS Max,
                    MAX(value) - MIN(value) AS Use2,
                    SUM(overlap_use) AS Use,
                    MIN(end_time) AS First,
                    MAX(end_time) AS Last,
                    date_diff('minute', MIN(eff_start), MAX(eff_end)) AS Mins
                FROM interval_overlaps
                GROUP BY name, begin, fin
            )
            SELECT 
                name, begin, fin, Min, Max, Use2, Use, First, Last, Mins,
                24.0 * 60.0 * Use / NULLIF(Mins, 0) AS "Use/Day",
                365.25 * 24.0 * 60.0 * Use / NULLIF(Mins, 0) AS "Use/Year",
                {price} * 24.0 * 60.0 * Use / NULLIF(Mins, 0) AS "Daily Exp",
                {price} * 365.25 * 24.0 * 60.0 * Use / NULLIF(Mins, 0) AS "Yearly Exp"
            FROM agg
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
    m_id = meterid.get(minute_table)
    if begin is None:
        with duckdb.connect(duckdb_file) as con:
            begin = con.sql(f"SELECT MIN(start_time) FROM strom_intervals WHERE meterid IN {m_id}").fetchone()[0]

    if fin is None:
        with duckdb.connect(duckdb_file) as con:
            fin = con.sql(f"SELECT MAX(end_time) FROM strom_intervals WHERE meterid IN {m_id}").fetchone()[0]

    price = strom_prices.get(minute_table)

    with duckdb.connect(duckdb_file) as con:
        strom_avg = con.sql(
            f"""
            WITH interval_overlaps AS (
                SELECT 
                    d.value,
                    d.end_time,
                    d.start_time,
                    cm * date_diff('minute', greatest(d.start_time, CAST('{begin}' AS DATETIME)), least(d.end_time, CAST('{fin}' AS DATETIME))) AS overlap_use,
                    greatest(d.start_time, CAST('{begin}' AS DATETIME)) AS eff_start,
                    least(d.end_time, CAST('{fin}' AS DATETIME)) AS eff_end
                FROM strom_intervals d
                WHERE d.meterid IN {m_id}
                  AND d.start_time < CAST('{fin}' AS DATETIME) 
                  AND d.end_time > CAST('{begin}' AS DATETIME)
            ),
            agg AS (
                SELECT 
                    MIN(value) AS Min,
                    MAX(value) AS Max,
                    MAX(value) - MIN(value) AS Use2,
                    SUM(overlap_use) AS Use,
                    MIN(end_time) AS First,
                    MAX(end_time) AS Last,
                    date_diff('minute', MIN(eff_start), MAX(eff_end)) AS Mins
                FROM interval_overlaps
            )
            SELECT 
                Min, Max, Use2, Use, First, Last, Mins,
                24.0 * 60.0 * Use / NULLIF(Mins, 0) AS "Use/Day",
                365.25 * 24.0 * 60.0 * Use / NULLIF(Mins, 0) AS "Use/Year",
                {price} * 24.0 * 60.0 * Use / NULLIF(Mins, 0) AS "Daily Exp",
                {price} * 365.25 * 24.0 * 60.0 * Use / NULLIF(Mins, 0) AS "Yearly Exp"
            FROM agg
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
            begin = con.sql("SELECT MIN(date) FROM strom_per_day").fetchone()[0]

    if fin is None:
        with duckdb.connect(duckdb_file) as con:
            fin = con.sql("SELECT MAX(date) FROM strom_per_day").fetchone()[0]

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


@stepit
def compare_last_days(
    climate_daily,
    days=15,
    years_back=4,
    duckdb_file="./duckdb/strom.duckdb",
):
    with duckdb.connect(duckdb_file) as con:
        fin = con.sql("SELECT MAX(date) FROM strom_per_day").fetchone()[0]

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


@stepit
def normalstrom_consumption(duckdb_file, *args, **kwargs):
    return calculate_avg_consumption(
        minute_table="normalstrom_minute",
        duckdb_file=duckdb_file,
    )


@stepit
def waermestrom_consumption(duckdb_file, *args, **kwargs):
    return calculate_avg_consumption(
        minute_table="waermestrom_minute",
        duckdb_file=duckdb_file,
    )
