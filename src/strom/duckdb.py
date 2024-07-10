import duckdb

import pandas as pd


def duck_md5(con, tbl_name):
    """Calculate the MD5 checksum of all the data in the specified table.

    Args:
        con: The database connection object.
        tbl_name (str): The name of the table to calculate the MD5 checksum for.

    Returns:
        pandas.DataFrame: A DataFrame containing the MD5 checksum of the specified table.

    Raises:
        ValueError: If the table name is invalid.
    """
    # Validate table name
    if not isinstance(tbl_name, str) or not tbl_name.isidentifier():
        raise ValueError("Invalid table name.")

    query = f"SELECT md5(string_agg({tbl_name}::text, '')) FROM {tbl_name};"

    return con.sql(query).df()
