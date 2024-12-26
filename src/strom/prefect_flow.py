from prefect import flow, task, get_run_logger

from strom.prefect_ops import task_ops

from strom import meter, dwd, consumption, quarto

import pandas as pd

from datetime import date

import epyfun


@task(**task_ops)
def merge_strom_climate_data(strom_per_day, climate_daily):

    # strom_per_day = strom.read_result("make_strom_per_day")
    # climate_daily = strom.read_result("get_climate_data")

    strom_climate = pd.merge(
        strom_per_day,
        climate_daily,
        on="date",
        how="left",
        indicator=True,
        validate="one_to_one",
    )
    # WHERE minute <= '2021-05-25' OR minute >= '2022-11-30'
    # WHERE minute <= '2021-05-25' OR minute >= '2022-11-30'

    # only pass to strom_climate the data where we have actual observations
    period1_cond = (strom_climate["date"] >= "2020-12-01") & (
        strom_climate["date"] <= "2021-05-25"
    )
    period2_cond = strom_climate["date"] >= "2022-12-01"
    obs_cond = strom_climate["obs"] > 0
    strom_climate = strom_climate[period1_cond | period2_cond]

    # at tis point, there might still be NAs in the climate data
    for column in strom_climate.columns:
        if strom_climate[column].isna().any():
            # Apply forward fill to the column
            strom_climate[column] = strom_climate[column].ffill()

    return strom_climate


@flow(log_prints=True)
def strom_flow():
    """
    Given a GitHub repository, logs the number of stargazers
    and contributors for that repo.
    """

    duckdb_file = "./duckdb/strom.duckdb"
    epyfun.create_dir(duckdb_file)
    sqlite_file = epyfun.get_latest_file("./data/")
    logger = get_run_logger()
    logger.info(f"Current latest data file: {sqlite_file}")

    strom = meter.ingest_strom(sqlite_file, duckdb_file)
    strom_minute = meter.expand_strom_minute(strom, duckdb_file)
    strom_per_day = meter.make_strom_per_day(strom_minute, duckdb_file)
    strom_per_month = meter.make_strom_per_month(strom_minute, duckdb_file)
    strom_per_hour = meter.make_strom_per_hour(strom_minute, duckdb_file)
    # month

    climate_daily = dwd.get_climate_data(date.today())

    strom_climate = merge_strom_climate_data(strom_per_day, climate_daily)

    consumption.normalstrom_consumption(duckdb_file)
    consumption.waermestrom_consumption(duckdb_file)

    consumption.compare_last_days(climate_daily)
    ccomp = consumption.compare_last_days.with_options
    ccomp(result_storage_key="last_5_days")(climate_daily, 5)
    ccomp(result_storage_key="last_15_days")(climate_daily, 15)
    ccomp(result_storage_key="last_30_days")(climate_daily, 30)
    ccomp(result_storage_key="last_60_days")(climate_daily, 60)
    ccomp(result_storage_key="last_90_days")(climate_daily, 90)
    ccomp(result_storage_key="last_365_days")(climate_daily, 365.25)

    quarto.render_report(strom_climate)


if __name__ == "__main__":
    strom_flow()
