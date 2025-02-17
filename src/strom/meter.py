from stepit import stepit

import duckdb
from strom.duckdb import duck_md5


@stepit
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
                CASE WHEN first = 1 THEN NULL ELSE value - lag(value, 1) OVER(
                    PARTITION BY meterid 
                    ORDER BY date
                ) END AS consumption,
                1.0 * consumption / minutes AS cm
            FROM strom_sqlite
            ORDER BY date
            ;
            """
        )

        return duck_md5(con, "strom")


@stepit
def expand_strom_minute(strom, duckdb_file="./duckdb/strom.duckdb"):
    """Expand the 'strom' table to create a minute-by-minute table.

    This function does that by generating a series of minutes for each meterid
    (1 to 3) between the min and max dates in 'strom' and then joining the
    strom data to bring the measurement values to the minute-level granularity.
    The result is saved to the consumption table 'strom_minute', that includes
    the following columns:

    - meterid: int with the meter id, where 1 corresponds to normal strom and 2
      and 3 to wärmestrom in hoch and niedrig tariff, respectively.
    - minute: datetime (there will be one row per every minute in the
      observation period, for every meter).
      DONE: currently it generates to the actual first and last minute of
      measurement. But it may be worth expanding to the whole day. >>>
      Tried, date_trunc('day', ts[2]) + interval '1 day' - interval '1 minute'
      and, it seems to me it would be better to stick to the observation
      date (filling until the end of the day, would just extend the last
      measurement consumption to the rest of the day. That's fine, but, if
      you already have several observations within the day, perhaps it would
      be better to extrapolate using all those obs, and not just the last
      measurement.)
    - cm: consumption per minute, as calculated in the strom table
      (consumption/minutes) and extrapolated throughout the whole period.
      So we are making here a probably unrealistic assumption that the
      consumption between the different observations in the strom table is
      constant. But that's fine to get an approximation to the consumption,
      considering the relatively random-nature of the time of measurements.
      Thus, if we have cm_(i), calculated as
      cm_(i) = ( value_(t) - value_(t-1) ) / minutes
      then we will assing a constant cm_(i) to the whole period between
      t-1 and t.
    - date: datetime indicating when the measurement was recorded. This column
      will have a value only in the minute where the actual measurement took
      place and thus, will have NULL in all other minutes
      (the same applies for the columns below).
    - value: value of the meter at the given date
    - minutes: number of minutes between previous and current measurement.
    - consumption: consumption since the last measurement, calculated as
      value_(t) - value_(t-1)). Whenever there is a first measurement,
      consumption should be NA / NULL, because the meter started again and
      the comparison with the previous value is not relevant anymore.

    Finally, note the decorator. This is a prefect task, to be used within a
    prefect flow, gaining its benefits such as caching, logging, monitoring.
    That's also why we decided to return the md5 checksum of the data, to
    help prefect in tracking changes, without returning the whole table.

    Args:
        strom: Unused parameter. It's just a placeholder to be able to induce a
        dependency between this task and the previous task (strom) in the
        prefect workflow.
        duckdb_file (str, optional): Path to the DuckDB file. Defaults to "./duckdb/strom.duckdb".

    Returns:
        pd.DataFrame: A DataFrame containing a single column 'md5' with the MD5
        checksum of the 'strom_minute' table's contents.
    """

    with duckdb.connect(duckdb_file) as con:
        con.sql(
            """
            CREATE OR REPLACE TABLE strom_minute AS
            WITH minutes_table AS (
                SELECT 
                    UNNEST(generate_series(
                        ts[1], ts[2], interval 1 minute
                    )) AS minute, 
                    generate_series AS meterid
                FROM (VALUES ([(
                    SELECT MIN(date) FROM strom), (SELECT MAX(date) FROM strom)]
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
            ORDER BY minutes_table.minute, minutes_table.meterid
            ;
            """
        )

        return duck_md5(con, "strom_minute")


@stepit
def make_strom_per_day(strom_minute, duckdb_file="./duckdb/strom.duckdb"):
    with duckdb.connect(duckdb_file) as con:
        strom_per_day = con.sql(
            """
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


@stepit
def make_strom_per_month(strom_minute, duckdb_file="./duckdb/strom.duckdb"):
    with duckdb.connect(duckdb_file) as con:
        strom_per_day = con.sql(
            """
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
                        (minute >= '2020-12-01' AND minute <= '2021-04-30') 
                        OR 
                        (minute >= '2022-12-01' AND minute < (
                            SELECT DATE_TRUNC('month', MAX(minute))
                            FROM strom_minute
                        ))
                )
                PIVOT_WIDER cte
                ON meterid
                USING 
                    SUM(cm) AS cd,
                    SUM(CASE WHEN value IS NOT NULL THEN 1 ELSE 0 END) AS obs
                GROUP BY year, month
            )
            ;
            """
        )

        return con.sql("SELECT * FROM strom_per_month;").df()


@stepit
def make_strom_per_hour(strom_minute, duckdb_file="./duckdb/strom.duckdb"):
    with duckdb.connect(duckdb_file) as con:
        strom_per_day = con.sql(
            """
            CREATE OR REPLACE TABLE strom_per_hour AS
            SELECT 
                year, month, day, hour,
                "1_cd" AS nd,
                "2_cd" + "3_cd" AS wd,
                "2_cd" AS nt,
                "3_cd" AS ht,
                (("1_weight" + "2_weight" + "3_weight") / 3) AS weight
            FROM (
                WITH cte AS (
                    SELECT     
                        EXTRACT(YEAR FROM minute) AS year,    
                        EXTRACT(MONTH FROM minute) AS month,
                        EXTRACT(DAY FROM minute) AS day,
                        EXTRACT(HOUR FROM minute) AS hour,
                        1 / FIRST_VALUE(minutes IGNORE NULLS) OVER(
                            PARTITION BY meterid 
                            ORDER BY minute 
                            ROWS BETWEEN CURRENT ROW AND UNBOUNDED FOLLOWING 
                        ) AS weight,
                        * 
                    FROM strom_minute
                    WHERE 
                        (minute >= '2020-12-01' AND minute <= '2021-05-25') 
                        OR 
                        (minute >= '2022-12-01')
                )
                PIVOT_WIDER cte
                ON meterid
                USING 
                    SUM(cm) AS cd,
                    AVG(weight) AS weight
                GROUP BY year, month, day, hour
            )
            ;
            """
        )

        return con.sql("SELECT * FROM strom_per_hour;").df()
