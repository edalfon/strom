import epyfun
import numpy as np
import requests
from bs4 import BeautifulSoup
from stepit import stepit


@stepit
def get_climate_data(current_date):
    historical_files = download_climate_data(
        "https://opendata.dwd.de/climate_environment/CDC/observations_germany/climate/hourly/air_temperature/historical/"
    )
    recent_files = download_climate_data(
        "https://opendata.dwd.de/climate_environment/CDC/observations_germany/climate/hourly/air_temperature/recent/"
    )
    air = bind_rows_files(historical_files + recent_files)
    aircols = ["TT_TU", "RF_TU"]
    air.replace(-999, np.nan, inplace=True)

    historical_files = download_climate_data(
        "https://opendata.dwd.de/climate_environment/CDC/observations_germany/climate/hourly/dew_point/historical/"
    )
    recent_files = download_climate_data(
        "https://opendata.dwd.de/climate_environment/CDC/observations_germany/climate/hourly/dew_point/recent/"
    )
    dew = bind_rows_files(historical_files + recent_files)
    dewcols = ["  TT", "  TD"]
    dew.replace(-999, np.nan, inplace=True)

    historical_files = download_climate_data(
        "https://opendata.dwd.de/climate_environment/CDC/observations_germany/climate/hourly/moisture/historical/"
    )
    recent_files = download_climate_data(
        "https://opendata.dwd.de/climate_environment/CDC/observations_germany/climate/hourly/moisture/recent/"
    )
    moist = bind_rows_files(historical_files + recent_files)
    moistcols = ["VP_STD", "TF_STD", "P_STD", "TT_STD", "RF_STD", "TD_STD"]

    historical_files = download_climate_data(
        "https://opendata.dwd.de/climate_environment/CDC/observations_germany/climate/hourly/precipitation/historical/"
    )
    recent_files = download_climate_data(
        "https://opendata.dwd.de/climate_environment/CDC/observations_germany/climate/hourly/precipitation/recent/"
    )
    precip = bind_rows_files(historical_files + recent_files)
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
        .agg({key: ["min", "max", "mean", "median", "std"] for key in datacols})
        .reset_index()
    )
    climate_daily = epyfun.pandas.clean_names(agg_df)

    # climate_daily = strom.read_result("get_climate_data")

    # assert climate_daily.notna().all().all()

    # columns_with_na = climate_daily.columns[climate_daily.isna().any()].tolist()

    return climate_daily


def download_climate_data(listing_url):
    # Fetch HTML content
    response = requests.get(listing_url)
    html_content = response.text

    # Parse HTML content
    soup = BeautifulSoup(html_content, "html.parser")

    # Extract links that contains the stations ids, with the codes
    # for the stations of kiefersfelden or rosenheim
    target_links = [
        a["href"]
        for a in soup.find_all("a", href=True)
        if "_03679_" in a["href"] or "_04261_" in a["href"]
    ]

    downloaded_files = []
    for link in target_links:
        print("Downloading: ", link)
        epyfun.web.download_file(
            listing_url + "/" + link, "interim/climate/latest/" + link
        )
        downloaded_files.append("interim/climate/latest/" + link)

    return downloaded_files


import io
import zipfile

import pandas as pd


def read_csv_from_zip(zip_file_path):
    with zipfile.ZipFile(zip_file_path, "r") as zip_file:
        # Get the list of file names in the zip file
        file_names = zip_file.namelist()

        # Filter the file names that start with the specified prefix
        target_files = [
            file_name for file_name in file_names if file_name.startswith("produkt")
        ]

        print(target_files)
        if not target_files:
            raise Exception("No files start with produkt")
        if len(target_files) > 1:
            raise Exception(
                "There are more files that start with produkt. Double check"
            )

        target_file_name = target_files[0]

        # Read the CSV file directly from the zip archive using pandas
        with zip_file.open(target_file_name) as file_in_zip:
            df = pd.read_csv(
                io.TextIOWrapper(file_in_zip), sep=";"
            )  # Adjust the separator based on the file format

        return df


def bind_rows_files(all_files):
    # all_files = ["interim/climate/latest/stundenwerte_TU_04261_akt.zip",
    # "./interim/climate/latest/stundenwerte_TU_04261_20060301_20221231_hist.zip"]
    # read_csv_from_zip("interim/climate/latest/stundenwerte_TU_04261_akt.zip")
    all_dfs = [read_csv_from_zip(file) for file in all_files]
    result_df = pd.concat(all_dfs, ignore_index=True)
    result_df["MESS_DATUM"] = pd.to_datetime(result_df["MESS_DATUM"], format="%Y%m%d%H")

    return result_df
