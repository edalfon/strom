from stepit import stepit

import duckdb
from strom.duckdb import duck_md5


# Shared window-function SQL that turns a (meterid, date, value, first) source
# into the 'strom' table (minutes/consumption/cm columns added). Used by both
# the sqlite-based ingest_strom below and gsheets.ingest_strom_gsheet, so the
# two sources can never compute consumption differently.
STROM_WINDOW_SQL = """
CREATE OR REPLACE TABLE strom AS
SELECT
    *,
    date_sub(
        'minute',
        lag(date, 1) OVER(PARTITION BY meterid ORDER BY date),
        date
    ) AS minutes,
    CASE WHEN first = 1 THEN NULL ELSE value - lag(value, 1) OVER(
        PARTITION BY meterid
        ORDER BY date
    ) END AS consumption,
    1.0 * consumption / minutes AS cm
FROM {source}
ORDER BY date
;
"""


# @stepit
def ingest_strom(sqlite_file, duckdb_file="./duckdb/strom.duckdb"):
    """Ingest strom measurements data into a DuckDB table named 'strom'.

    This function reads the raw data from a SQLite file containing meter
    data. In such data, every row is one measurement for a given meter
    (meterid). The function ingest that into the 'strom' table in duckdb,
    that includes the following columns:

    - meterid: int with the meter id, where 1 corresponds to normal strom and 2
      and 3 to wärmestrom in hoch and niedrig tariff, respectively.
    - date: datetime of the measurement.
    - value: value of the meter at the measurement datetime.
    - first: dummy variable, where 1 indicates that it is a first measurement
     (e.g. the beginning of all time, or when meter is changes or restarted).
    - minutes: number of minutes between previous and current measurement.
    - consumption: consumption since the last measurement, calculated as
      value_(t) - value_(t-1)). Whenever there is a first measurement,
      consumption should be NA / NULL, because the meter started again and
      the comparison with the previous value is not relevant anymore.
    - cm: consumption per minute, calculated as consumption / minutes.

    Finally, note the decorator. This is a prefect task, to be used within a
    prefect flow, gaining its benefits such as caching, logging, monitoring.
    That's also why we decided to return the md5 checksum of the data, to
    help prefect in tracking changes, without returning the whole table.

    Args:
        sqlite_file: Path to the SQLite file containing the electricity data.
        duckdb_file: Path to the DuckDB database file
                     (defaults to "./duckdb/strom.duckdb").

    Returns:
        A pandas DataFrame containing a single row with the column 'md5'
        containing the checksum of the whole table.
    """
    with duckdb.connect(duckdb_file) as con:
        con.install_extension("sqlite")  # con.sql("INSTALL sqlite;")
        con.load_extension("sqlite")  # con.sql("LOAD sqlite;")
        con.sql(
            f"""
            CREATE OR REPLACE VIEW strom_sqlite AS
            SELECT
                meterid,
                -- Blob Functions, because most columns get read as blob
                -- https://duckdb.org/docs/sql/functions/blob
                CAST(decode(date) AS DATETIME) AS date,
                CAST(decode(value) AS INT) AS value,
                CAST(decode(first) AS INT) AS first
            FROM sqlite_scan('{sqlite_file}', 'reading')
            WHERE meterid = 1 OR meterid = 2 OR meterid = 3
            ;
            """
        )
        con.sql(STROM_WINDOW_SQL.format(source="strom_sqlite"))

        return duck_md5(con, "strom")


# @stepit
def make_strom_intervals(strom, duckdb_file="./duckdb/strom.duckdb"):
    """Create a table of observation intervals from the 'strom' table.

    This function replaces the old minute-by-minute expansion strategy with
    a much more computationally efficient interval-based approach. We compute
    the start and end times of each interval, which exactly covers the valid
    time bounds inside DuckDB without blowing up row counts.

    Args:
        strom: Unused parameter. It's just a placeholder to be able to induce a
        dependency between this task and the previous task (strom) in the
        prefect workflow.
        duckdb_file (str, optional): Path to the DuckDB file. Defaults to "./duckdb/strom.duckdb".

    Returns:
        pd.DataFrame: A DataFrame containing a single column 'md5' with the MD5
        checksum of the 'strom_intervals' table's contents.
    """

    with duckdb.connect(duckdb_file) as con:
        con.sql(
            """
            CREATE OR REPLACE TABLE strom_intervals AS
            SELECT 
                meterid,
                date - minutes * INTERVAL 1 MINUTE AS start_time,
                date AS end_time,
                minutes AS interval_minutes,
                cm,
                value IS NOT NULL AS has_obs,
                value,
                consumption
            FROM strom
            WHERE first = 0 OR cm IS NOT NULL
            ;
            """
        )

        return duck_md5(con, "strom_intervals")


@stepit
def make_strom_per_day(strom_intervals, duckdb_file="./duckdb/strom.duckdb"):
    with duckdb.connect(duckdb_file) as con:
        strom_per_day = con.sql(
            """
            CREATE OR REPLACE TABLE strom_per_day AS
            SELECT 
                date,
                COALESCE("1_cd", 0) AS nd,
                COALESCE("2_cd", 0) + COALESCE("3_cd", 0) AS wd,
                COALESCE("2_cd", 0) AS nt,
                COALESCE("3_cd", 0) AS ht,
                GREATEST(COALESCE("1_obs", 0), COALESCE("2_obs", 0), COALESCE("3_obs", 0)) AS obs
            FROM (
                WITH days AS (
                    SELECT UNNEST(generate_series(
                        (SELECT date_trunc('day', MIN(start_time)) FROM strom_intervals),
                        (SELECT date_trunc('day', MAX(end_time)) FROM strom_intervals),
                        INTERVAL 1 DAY
                    )) AS date
                ),
                day_overlaps AS (
                    SELECT 
                        d.date,
                        s.meterid,
                        s.cm,
                        date_diff('minute', 
                            greatest(s.start_time, d.date), 
                            least(s.end_time, d.date + INTERVAL 1 DAY)
                        ) AS overlap_minutes,
                        CASE WHEN date_trunc('day', s.end_time) = d.date THEN s.has_obs ELSE false END AS has_obs
                    FROM days d
                    JOIN strom_intervals s
                        ON s.start_time < (d.date + INTERVAL 1 DAY) 
                       AND s.end_time > d.date
                ),
                cte AS (
                    SELECT 
                        date,
                        meterid,
                        SUM(cm * overlap_minutes) AS tot,
                        SUM(cm * overlap_minutes) / NULLIF(SUM(overlap_minutes), 0) * 24.0 * 60.0 AS cd,
                        SUM(CASE WHEN has_obs THEN 1 ELSE 0 END) AS obs
                    FROM day_overlaps
                    GROUP BY date, meterid
                )
                PIVOT_WIDER cte
                ON meterid
                USING 
                    SUM(tot) AS tot,
                    SUM(cd) AS cd, 
                    SUM(obs) AS obs
                GROUP BY date
            )
            ORDER BY date
            ;
            """
        )

        return con.sql("SELECT * FROM strom_per_day;").df()


@stepit
def make_strom_per_month(strom_intervals, duckdb_file="./duckdb/strom.duckdb"):
    with duckdb.connect(duckdb_file) as con:
        strom_per_month = con.sql(
            """
            CREATE OR REPLACE TABLE strom_per_month AS
            SELECT 
                year, month,
                COALESCE("1_cd", 0) AS nd,
                COALESCE("2_cd", 0) + COALESCE("3_cd", 0) AS wd,
                COALESCE("2_cd", 0) AS nt,
                COALESCE("3_cd", 0) AS ht,
                GREATEST(COALESCE("1_obs", 0), COALESCE("2_obs", 0), COALESCE("3_obs", 0)) AS obs
            FROM (
                WITH months AS (
                    SELECT UNNEST(generate_series(
                        (SELECT date_trunc('month', MIN(start_time)) FROM strom_intervals),
                        (SELECT date_trunc('month', MAX(end_time)) FROM strom_intervals),
                        INTERVAL 1 MONTH
                    )) AS month_start
                ),
                month_overlaps AS (
                    SELECT 
                        m.month_start,
                        s.meterid,
                        s.cm,
                        date_diff('minute', 
                            greatest(s.start_time, m.month_start), 
                            least(s.end_time, m.month_start + INTERVAL 1 MONTH)
                        ) AS overlap_minutes,
                        CASE WHEN date_trunc('month', s.end_time) = m.month_start THEN s.has_obs ELSE false END AS has_obs
                    FROM months m
                    JOIN strom_intervals s
                        ON s.start_time < (m.month_start + INTERVAL 1 MONTH) 
                       AND s.end_time > m.month_start
                ),
                cte AS (
                    SELECT     
                        EXTRACT(YEAR FROM month_start) AS year,    
                        EXTRACT(MONTH FROM month_start) AS month,
                        meterid,
                        SUM(cm * overlap_minutes) AS cd,
                        SUM(CASE WHEN has_obs THEN 1 ELSE 0 END) AS obs
                    FROM month_overlaps
                    WHERE 
                        (month_start >= '2020-12-01' AND month_start <= '2021-04-30') 
                        OR 
                        (month_start >= '2022-12-01' AND month_start < (
                            SELECT DATE_TRUNC('month', MAX(end_time))
                            FROM strom_intervals
                        ))
                    GROUP BY year, month, meterid
                )
                PIVOT_WIDER cte
                ON meterid
                USING 
                    SUM(cd) AS cd,
                    SUM(obs) AS obs
                GROUP BY year, month
            )
            ORDER BY year, month
            ;
            """
        )

        return con.sql("SELECT * FROM strom_per_month;").df()


@stepit
def make_strom_per_hour(strom_intervals, duckdb_file="./duckdb/strom.duckdb"):
    with duckdb.connect(duckdb_file) as con:
        strom_per_hour = con.sql(
            """
            CREATE OR REPLACE TABLE strom_per_hour AS
            SELECT 
                year, month, day, hour,
                COALESCE("1_cd", 0) AS nd,
                COALESCE("2_cd", 0) + COALESCE("3_cd", 0) AS wd,
                COALESCE("2_cd", 0) AS nt,
                COALESCE("3_cd", 0) AS ht,
                ((COALESCE("1_weight", 0) + COALESCE("2_weight", 0) + COALESCE("3_weight", 0)) / 3) AS weight
            FROM (
                WITH hours AS (
                    SELECT UNNEST(generate_series(
                        (SELECT date_trunc('hour', MIN(start_time)) FROM strom_intervals),
                        (SELECT date_trunc('hour', MAX(end_time)) FROM strom_intervals),
                        INTERVAL 1 HOUR
                    )) AS hour_start
                ),
                hour_overlaps AS (
                    SELECT 
                        h.hour_start,
                        s.meterid,
                        s.cm,
                        1.0 * date_diff('minute', 
                            greatest(s.start_time, h.hour_start), 
                            least(s.end_time, h.hour_start + INTERVAL 1 HOUR)
                        ) / NULLIF(s.interval_minutes, 0) AS weight_overlap,
                        date_diff('minute', 
                            greatest(s.start_time, h.hour_start), 
                            least(s.end_time, h.hour_start + INTERVAL 1 HOUR)
                        ) AS overlap_minutes
                    FROM hours h
                    JOIN strom_intervals s
                        ON s.start_time < (h.hour_start + INTERVAL 1 HOUR) 
                       AND s.end_time > h.hour_start
                ),
                cte AS (
                    SELECT     
                        EXTRACT(YEAR FROM hour_start) AS year,    
                        EXTRACT(MONTH FROM hour_start) AS month,
                        EXTRACT(DAY FROM hour_start) AS day,
                        EXTRACT(HOUR FROM hour_start) AS hour,
                        meterid,
                        SUM(cm * overlap_minutes) AS cd,
                        SUM(weight_overlap) / 60.0 AS weight
                    FROM hour_overlaps
                    WHERE 
                        (hour_start >= '2020-12-01' AND hour_start <= '2021-05-25') 
                        OR 
                        (hour_start >= '2022-12-01')
                    GROUP BY year, month, day, hour, meterid
                )
                PIVOT_WIDER cte
                ON meterid
                USING 
                    SUM(cd) AS cd,
                    SUM(weight) AS weight
                GROUP BY year, month, day, hour
            )
            ORDER BY year, month, day, hour
            ;
            """
        )

        return con.sql("SELECT * FROM strom_per_hour;").df()
