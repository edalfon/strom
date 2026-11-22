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

    # string_agg needs an ORDER BY: otherwise rows are concatenated in scan
    # order, which is not guaranteed, and the same data can give a different
    # checksum (spuriously invalidating the downstream cache)
    query = f"""
        SELECT md5(string_agg(row_text, '' ORDER BY row_text)) AS md5
        FROM (SELECT {tbl_name}::text AS row_text FROM {tbl_name});
    """

    return con.sql(query).df()
