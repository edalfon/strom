from strom import meter

import duckdb

duckdb_file = "./duckdb/test.duckdb"


def test_ingest_normalstrom():
    # test it creates the table and returns an expected hash md5 value
    md5 = meter.ingest_normalstrom.fn(
        "data/2022-12-24-ecas-export.db", duckdb_file=duckdb_file
    )
    assert md5["md5"].item() == "0ab1d288e32f2f020d2f63de704c98d6"

    with duckdb.connect(duckdb_file) as con:
        normalstrom = con.sql("SELECT * FROM normalstrom;").df()
        normalstrom.columns
