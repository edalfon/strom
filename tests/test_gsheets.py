import os

import duckdb
import pytest
import toml

from strom import gsheets

duckdb_file = "./duckdb/test_gsheets.duckdb"

requires_credentials = pytest.mark.skipif(
    "GOOGLE_SHEETS_CREDENTIALS_JSON" not in os.environ,
    reason="GOOGLE_SHEETS_CREDENTIALS_JSON not set; skipping live Google Sheets test",
)


@requires_credentials
def test_ingest_strom_gsheet():
    config = toml.load("./config.toml")
    meters = {int(k): v for k, v in config["gsheets"]["meters"].items()}

    md5 = gsheets.ingest_strom_gsheet(
        config["gsheets"]["sheet_id"], meters, duckdb_file=duckdb_file
    )
    assert isinstance(md5["md5"].item(), str)
    assert len(md5["md5"].item()) == 32

    with duckdb.connect(duckdb_file) as con:
        strom = con.sql("SELECT * FROM strom;").df()

    expected_columns = {"meterid", "date", "value", "first", "minutes", "consumption", "cm"}
    assert expected_columns.issubset(set(strom.columns))
    assert len(strom) > 0
    assert set(strom["meterid"].unique()).issubset(set(meters.keys()))
