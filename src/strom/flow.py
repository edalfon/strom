from metaflow import FlowSpec, step

import duckdb
import epyfun

# pdm add -e file:///OneDrive/All/Python/epyfun --dev
# pdm add file:///OneDrive/All/Python/epyfun
import pandas as pd


class HelloFlow(FlowSpec):
    """
    A flow where Metaflow prints 'Hi'.

    Run this flow to validate that Metaflow is installed correctly.

    """

    @step
    def start(self):
        """
        This is the 'start' step. All flows must have a step named 'start' that
        is the first step in the flow.
        """
        self.sqlite_file = epyfun.get_latest_file("./data/")
        self.next(self.ingest_normalstrom)

    @step
    def ingest_normalstrom(self):
        with duckdb.connect("./duckdb/strom.duckdb") as con:
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
                    FROM sqlite_scan('{self.sqlite_file}', 'reading') 
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
        self.next(self.expand_normalstrom_minute)

    @step
    def expand_normalstrom_minute(self):
        with duckdb.connect("./duckdb/strom.duckdb") as con:
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
        self.next(self.ingest_waermestrom)

    @step
    def ingest_waermestrom(self):
        with duckdb.connect("./duckdb/strom.duckdb") as con:
            con.sql(
                f"""
                CREATE OR REPLACE TABLE waermestrom_nulls AS
                WITH
                ws181 AS (
                SELECT 
                    'Hoch' AS tariff,
                    decode(date)::DATETIME AS date, 
                    decode(value)::INT AS value
                FROM sqlite_scan('{self.sqlite_file}', 'reading') 
                WHERE meterid = 3 
                ),
                ws182 AS (
                SELECT 
                    'Niedrig' AS tariff, 
                    decode(date)::DATETIME AS date, 
                    decode(value)::INT AS value
                FROM sqlite_scan('{self.sqlite_file}', 'reading') 
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
        self.next(self.expand_waermestrom_minute)

    @step
    def expand_waermestrom_minute(self):
        with duckdb.connect("./duckdb/strom.duckdb") as con:
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
        self.next(self.get_climate_data)

    @step
    def get_climate_data(self):
        import dwd
        import numpy as np

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
        agg_df = epyfun.pandas.clean_names(agg_df)

        self.climate_daily = agg_df

        self.next(self.make_strom_per_day)

    @step
    def make_strom_per_day(self):
        with duckdb.connect("./duckdb/strom.duckdb") as con:
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
            self.strom_per_day = strom_per_day.drop(columns="nobs").rename(
                columns={"wobs": "obs"}
            )

        self.next(self.merge_strom_climate_data)

    @step
    def merge_strom_climate_data(self):
        self.strom_climate = pd.merge(
            self.strom_per_day, self.climate_daily, on="date", how="left"
        )
        self.next(self.end)

    @step
    def end(self):
        """
        This is the 'end' step. All flows must have an 'end' step, which is the
        last step in the flow.
        """
        print("HelloFlow is all done.")


if __name__ == "__main__":
    HelloFlow()
