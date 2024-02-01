from prefect import task

from strom.prefect_ops import task_ops

import duckdb
import pandas as pd


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
def normalstrom_consumption(duckdb_file, *args, **kwargs):
    return calculate_avg_consumption(
        minute_table="normalstrom_minute", price=0.3713, duckdb_file=duckdb_file
    )


@task(**task_ops)
def waermestrom_consumption(duckdb_file, *args, **kwargs):
    return calculate_avg_consumption(
        minute_table="waermestrom_minute", price=0.2763, duckdb_file=duckdb_file
    )
