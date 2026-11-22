import duckdb
import numpy as np

from strom import meter

SQLITE_FILE = "data/2022-12-24-ecas-export.db"


def test_ingest_strom(tmp_path):
    duckdb_file = str(tmp_path / "test.duckdb")

    md5 = meter.ingest_strom(SQLITE_FILE, duckdb_file=duckdb_file)
    md5 = md5["md5"].item()
    assert isinstance(md5, str) and len(md5) == 32

    # same input -> same checksum (it is the change signal for the cache)
    assert meter.ingest_strom(SQLITE_FILE, duckdb_file=duckdb_file)["md5"].item() == md5

    with duckdb.connect(duckdb_file) as con:
        strom = con.sql("SELECT * FROM strom ORDER BY meterid, date").df()

    assert len(strom) > 0
    assert {"meterid", "date", "value", "first", "minutes", "consumption", "cm"}.issubset(
        strom.columns
    )
    assert set(strom["meterid"].unique()).issubset({1, 2, 3})

    # a (re)start of the meter has no consumption
    assert strom.loc[strom["first"] == 1, "consumption"].isna().all()

    # consumption is the difference to the previous reading of the same meter,
    # and cm is consumption per minute
    rest = strom[strom["first"] != 1].dropna(subset=["consumption"])
    assert len(rest) > 0
    prev = strom.groupby("meterid")["value"].shift(1).loc[rest.index]
    np.testing.assert_allclose(rest["consumption"], rest["value"] - prev)
    np.testing.assert_allclose(rest["cm"], rest["consumption"] / rest["minutes"])


def test_duck_md5_does_not_depend_on_row_order():
    from strom.duckdb import duck_md5

    with duckdb.connect() as con:
        con.sql("CREATE TABLE a AS SELECT * FROM range(5000) t(i)")
        con.sql("CREATE TABLE b AS SELECT * FROM range(5000) t(i) ORDER BY i DESC")
        assert duck_md5(con, "a")["md5"].item() == duck_md5(con, "b")["md5"].item()
