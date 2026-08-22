import json
import os

import duckdb
import gspread
import pandas as pd
from dotenv import load_dotenv

from strom.duckdb import duck_md5
from strom.meter import STROM_WINDOW_SQL

load_dotenv()

READONLY_SCOPES = ("https://www.googleapis.com/auth/spreadsheets.readonly",)


def _client():
    info = json.loads(os.environ["GOOGLE_SHEETS_CREDENTIALS_JSON"])
    return gspread.service_account_from_dict(info, scopes=READONLY_SCOPES)


# Google Sheets' date/time serial epoch (days since this date). Distinct from
# Excel's nominal 1899-12-31 epoch: Sheets doesn't replicate Excel's fictitious
# 1900-02-29 leap-year bug, so 1899-12-30 is the correct origin here.
SHEETS_EPOCH = "1899-12-30"


def _parse_sheet_date(value):
    # A manually-typed date/time is stored by Sheets as a real value and comes
    # back from the API (with UNFORMATTED_VALUE) as a numeric day-serial,
    # rendered elsewhere per the spreadsheet's locale (e.g. "8/22/2026
    # 9:39:03") -- ambiguous to parse as text (day/month order). Older rows
    # migrated from the sqlite archive were written in as literal ISO text
    # instead, so both a number and a string can legitimately show up in the
    # same column; handle both explicitly rather than guessing from a string.
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return pd.Timestamp(SHEETS_EPOCH) + pd.to_timedelta(value, unit="D")
    return pd.to_datetime(value, errors="coerce")


def _read_meter_worksheet(sh, meterid, name):
    ws = sh.worksheet(f"{meterid} {name}")
    # UNFORMATTED_VALUE (raw values) instead of get_all_records()'s default
    # FORMATTED_VALUE (locale-rendered display strings): a formatted numeric
    # reading like "12,165" would fail to parse and silently drop the row,
    # and a formatted date string is ambiguous to reparse (see above).
    rows = ws.get_all_values(value_render_option="UNFORMATTED_VALUE")
    if not rows:
        return pd.DataFrame(columns=["meterid", "date", "value", "first"])

    header, *records = rows
    records = [row + [""] * (len(header) - len(row)) for row in records]
    df = pd.DataFrame(records, columns=header)

    df["date"] = df["date"].apply(_parse_sheet_date)
    df["value"] = pd.to_numeric(df["value"], errors="coerce")
    df["first"] = pd.to_numeric(df["first"], errors="coerce").fillna(0).astype(int)

    n_before = len(df)
    df = df.dropna(subset=["date", "value"])
    if len(df) < n_before:
        print(f"warning: dropped {n_before - len(df)} invalid row(s) from tab '{ws.title}'")

    df["meterid"] = meterid
    return df[["meterid", "date", "value", "first"]]


# No @stepit here: this function's output (the md5 it returns) IS the
# change-detection signal that stepit/Prefect use to decide whether the
# downstream tasks need to rerun. It must run on every invocation (including
# every scheduled poll) to actually detect whether the sheet changed.
def ingest_strom_gsheet(sheet_id, meters, duckdb_file="./duckdb/strom.duckdb"):
    """Ingest strom measurements from a Google Sheet into a DuckDB 'strom' table.

    Mirrors meter.ingest_strom, but reads from a Google Sheet (one worksheet
    per meter, named "{meterid} {name}") instead of a sqlite export. Applies
    the same STROM_WINDOW_SQL used by the sqlite path, so both sources compute
    minutes/consumption/cm identically.

    Args:
        sheet_id: The Google Sheet's ID (the segment between /d/ and /edit in
            its URL).
        meters: Mapping of meterid (int) to meter name (str), used to look up
            each meter's worksheet by its "{meterid} {name}" title.
        duckdb_file: Path to the DuckDB database file
                     (defaults to "./duckdb/strom.duckdb").

    Returns:
        A pandas DataFrame containing a single row with the column 'md5'
        containing the checksum of the whole 'strom' table.
    """
    sh = _client().open_by_key(sheet_id)

    strom_raw = pd.concat(
        [_read_meter_worksheet(sh, meterid, name) for meterid, name in meters.items()],
        ignore_index=True,
    )

    with duckdb.connect(duckdb_file) as con:
        con.register("strom_raw", strom_raw)
        con.sql(STROM_WINDOW_SQL.format(source="strom_raw"))

        return duck_md5(con, "strom")
