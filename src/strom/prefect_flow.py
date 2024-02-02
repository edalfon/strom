from prefect import flow, task

from prefect.tasks import task_input_hash
from prefect.filesystems import LocalFileSystem

from strom.prefect_ops import task_ops

from strom import meter
from strom import dwd
from strom import consumption
from strom import quarto

import pandas as pd
import numpy as np

from datetime import date, time

import epyfun
import duckdb

import json
from prefect.results import PersistedResultBlob
from prefect.serializers import PickleSerializer, JSONSerializer


def read_result(
    filename: str, storage=task_ops["result_storage"], serialier: str = "pickle"
):
    path = storage._resolve_path(filename)
    with open(path, "rb") as buffered_reader:
        dict_obj = json.load(buffered_reader)
        blob = PersistedResultBlob.parse_obj(dict_obj)
    if serialier == "json":
        result = JSONSerializer().loads(blob.data)
    else:
        result = PickleSerializer().loads(blob.data)
    return result


@task(**task_ops)
def merge_strom_climate_data(strom_per_day, climate_daily):
    strom_climate = pd.merge(strom_per_day, climate_daily, on="date", how="left")
    return strom_climate


@flow(log_prints=True)
def strom_flow(refresh_cache=False):
    """
    Given a GitHub repository, logs the number of stargazers
    and contributors for that repo.
    """

    print("PREFECT RUNNING ...")

    duckdb_file = "./duckdb/strom.duckdb"
    epyfun.create_dir(duckdb_file)
    sqlite_file = epyfun.get_latest_file("./data/")

    normalstrom = meter.ingest_normalstrom(sqlite_file, duckdb_file)
    normalstrom_minute = meter.expand_normalstrom_minute(normalstrom, duckdb_file)

    waermestrom = meter.ingest_waermestrom(sqlite_file, duckdb_file)
    waermestrom_minute = meter.expand_waermestrom_minute(waermestrom, duckdb_file)

    strom_per_day = meter.make_strom_per_day(
        normalstrom_minute, waermestrom_minute, duckdb_file
    )
    climate_daily = dwd.get_climate_data(date.today())

    strom_climate = merge_strom_climate_data(strom_per_day, climate_daily)

    consumption.normalstrom_consumption(duckdb_file, normalstrom_minute)
    consumption.waermestrom_consumption(duckdb_file, waermestrom_minute)

    from datetime import datetime, timedelta

    consumption.calculate_avg_consumption(
        periods={
            "name": ["last 30 days"],
            "begin": [str(datetime.now().date() - timedelta(days=30))],
            "fin": [str(datetime.now().date())],
        },
        minute_table="waermestrom_minute",
        price=0.2763,
    )

    quarto.render_report(strom_climate)


if __name__ == "__main__":
    strom_flow()
