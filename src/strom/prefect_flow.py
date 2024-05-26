from prefect import flow, task, get_run_logger

from strom.prefect_ops import task_ops

from strom import meter, dwd, consumption, quarto

import pandas as pd

from datetime import date

import epyfun


@task(**task_ops)
def merge_strom_climate_data(strom_per_day, climate_daily):
    strom_climate = pd.merge(strom_per_day, climate_daily, on="date", how="left")
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

    normalstrom = meter.ingest_normalstrom(sqlite_file, duckdb_file)
    normalstrom_minute = meter.expand_normalstrom_minute(normalstrom, duckdb_file)

    waermestrom = meter.ingest_waermestrom(sqlite_file, duckdb_file)
    waermestrom_minute = meter.expand_waermestrom_minute(waermestrom, duckdb_file)

    strom_per_day = meter.make_strom_per_day(
        normalstrom_minute, waermestrom_minute, duckdb_file
    )
    climate_daily = dwd.get_climate_data(date.today())

    strom_climate = merge_strom_climate_data(strom_per_day, climate_daily)

    # strom_prices = consumption.ingest_prices()

    consumption.normalstrom_consumption(duckdb_file, normalstrom_minute)
    consumption.waermestrom_consumption(duckdb_file, waermestrom_minute)

    consumption.compare_last_days()
    consumption.compare_last_days.with_options(result_storage_key="last_5_days")(5)
    consumption.compare_last_days.with_options(result_storage_key="last_15_days")(15)
    consumption.compare_last_days.with_options(result_storage_key="last_30_days")(30)
    consumption.compare_last_days.with_options(result_storage_key="last_60_days")(60)
    consumption.compare_last_days.with_options(result_storage_key="last_90_days")(90)
    consumption.compare_last_days.with_options(result_storage_key="last_365_days")(
        365.25
    )

    quarto.render_report(strom_climate)

    # WHERE minute <= '2021-05-25' OR minute >= '2022-11-30'
    # WHERE minute <= '2021-05-25' OR minute >= '2022-11-30'


if __name__ == "__main__":
    strom_flow()
