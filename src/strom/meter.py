from prefect import task

from strom.prefect_ops import task_ops

import duckdb
import pandas as pd


@task(**task_ops)
def ingest_strom(sqlite_file, duckdb_file="./duckdb/strom.duckdb"):
    """Ingest data into `normalstrom` table.

    Returns:
        pandas.DataFrame: A DataFrame containing the MD5 checksum of the 'normalstrom' table.
    """
    with duckdb.connect(duckdb_file) as con:
        con.install_extension("sqlite")  # con.sql("INSTALL sqlite;")
        con.load_extension("sqlite")  # con.sql("LOAD sqlite;")
        con.sql(
            f"""
            CREATE OR REPLACE TABLE strom AS
            WITH strom_sqlite AS (
                SELECT 
                    meterid, 
                    -- Blob Functions, because most columns get read as blob
                    -- https://duckdb.org/docs/sql/functions/blob
                    CAST(decode(date) AS DATETIME) AS date, 
                    CAST(decode(value) AS INT) AS value,
                    CAST(decode(first) AS INT) AS first
                FROM sqlite_scan('{sqlite_file}', 'reading') 
                WHERE meterid = 1 OR meterid = 2 OR meterid = 3
            )
            SELECT 
                *,
                date_sub(
                    'minute', 
                    lag(date, 1) OVER(PARTITION BY meterid ORDER BY date),
                    date
                ) AS minutes, 
                -- use (1/(1-first)) to induce NA when it is first measurement
                value * (1/(1-first)) - lag(value, 1) OVER(
                    PARTITION BY meterid 
                    ORDER BY date
                ) AS consumption,
                1.0 * consumption / minutes AS cm
            FROM strom_sqlite
            ORDER BY date
            ;
            """
        )
        strom_md5 = con.sql(
            """
            SELECT md5(string_agg(strom::text, '')) AS md5 
            FROM strom;
            """
        ).df()
        return strom_md5


@task(**task_ops)
def expand_strom_minute(normalstrom, duckdb_file="./duckdb/strom.duckdb"):
    with duckdb.connect(duckdb_file) as con:
        con.sql(
            f"""
            CREATE OR REPLACE TABLE strom_minute AS
            WITH minutes_table AS (
            SELECT 
              UNNEST(generate_series(ts[1], ts[2], interval 1 minute)) 
                AS minute, 
              generate_series AS meterid
            FROM (VALUES (
                [(SELECT MIN(date) FROM strom), (SELECT MAX(date) FROM strom)]
            )) t(ts), generate_series(1, 3)
            )
            SELECT 
            minutes_table.meterid,
            minutes_table.minute,
            FIRST_VALUE(strom.cm IGNORE NULLS) OVER(
                PARTITION BY minutes_table.meterid 
                ORDER BY minutes_table.minute 
                ROWS BETWEEN CURRENT ROW AND UNBOUNDED FOLLOWING 
            ) AS cm,
            strom.date,
            strom.value,
            strom.minutes,
            strom.consumption 
            FROM minutes_table
            LEFT JOIN strom
            ON minutes_table.minute = strom.date AND 
               minutes_table.meterid = strom.meterid
            ORDER BY minutes_table.minute
            ;
            """
        )

        return con.sql(
            "SELECT md5(string_agg(strom_minute::text, '')) FROM strom_minute;"
        ).df()


@task(**task_ops)
def make_strom_per_day(strom_minute, duckdb_file="./duckdb/strom.duckdb"):
    with duckdb.connect(duckdb_file) as con:
        strom_per_day = con.sql(
            f"""
            CREATE OR REPLACE TABLE strom_per_day AS
            SELECT 
                date,
                "1_cd" AS nd,
                "2_cd" + "3_cd" AS wd,
                "2_cd" AS nt,
                "3_cd" AS ht,
                GREATEST("1_obs", "2_obs", "3_obs") AS obs
            FROM (
                WITH cte AS (
                    SELECT CAST(minute AS DATE) AS date, * FROM strom_minute
                )
                PIVOT_WIDER cte
                ON meterid
                USING 
                    SUM(cm) AS tot,
                    AVG(cm* 24.0 * 60.0)  AS cd, 
                    SUM(CASE WHEN value IS NOT NULL THEN 1 ELSE 0 END) AS obs
                GROUP BY date
            )
            ;
            """
        )

        return con.sql("SELECT * FROM strom_per_day;").df()


@task(**task_ops)
def make_strom_per_month(strom_minute, duckdb_file="./duckdb/strom.duckdb"):
    with duckdb.connect(duckdb_file) as con:
        strom_per_day = con.sql(
            f"""
            CREATE OR REPLACE TABLE strom_per_month AS
            SELECT 
                year, month,
                "1_cd" AS nd,
                "2_cd" + "3_cd" AS wd,
                "2_cd" AS nt,
                "3_cd" AS ht,
                GREATEST("1_obs", "2_obs", "3_obs") AS obs
            FROM (
                WITH cte AS (
                    SELECT     
                    EXTRACT(YEAR FROM minute) AS year,    
                    EXTRACT(MONTH FROM minute) AS month,
                    * 
                    FROM strom_minute
                    WHERE 
                        (minute >= '2020-12-01' AND minute <= '2021-05-31') OR 
                        (minute >= '2022-12-01')
                )
                PIVOT_WIDER cte
                ON meterid
                USING 
                    SUM(cm) AS cd,
                    --AVG(cm* 24.0 * 60.0)  AS cd, 
                    SUM(CASE WHEN value IS NOT NULL THEN 1 ELSE 0 END) AS obs
                GROUP BY year, month
            )
            ;
            """
        )

        return con.sql("SELECT * FROM strom_per_month;").df()
