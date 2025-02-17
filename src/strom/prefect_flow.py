from datetime import date

import epyfun
import pandas as pd
from stepit import stepit

from strom import consumption, dwd, meter


@stepit
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


def strom_flow():
    """
    Given a GitHub repository, logs the number of stargazers
    and contributors for that repo.
    """

    duckdb_file = "./duckdb/strom.duckdb"
    epyfun.create_dir(duckdb_file)
    sqlite_file = epyfun.get_latest_file("./data/")

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
    ccomp = consumption.compare_last_days.update
    ccomp(key="last_5_days")(climate_daily, 5)
    ccomp(key="last_15_days")(climate_daily, 15)
    ccomp(key="last_30_days")(climate_daily, 30)
    ccomp(key="last_60_days")(climate_daily, 60)
    ccomp(key="last_90_days")(climate_daily, 90)
    ccomp(key="last_365_days")(climate_daily, 365.25)

    # X_train, y_train, X_test, y_test = modelling.split_data(strom_climate)
    # all_models = modelling.get_models()

    # model_assessments = {
    #     key: modelling.assess_model.with_options(key=key)(
    #         model, X_train, y_train, X_test, y_test
    #     )
    #     for key, model in all_models.items()
    # }

    # interim = all_models["poly"]
    # x = modelling.assess_model.with_options(key="wow2")(
    #     interim, X_train, y_train, X_test, y_test
    # )

    # interim = all_models["poly"]
    # wow2 = modelling.assess_model(interim, X_train, y_train, X_test, y_test)
    # print(wow2[0])
    # wow = modelling.fit_model(interim, X_train, y_train)
    # print(wow)

    # Try writing a custom cache function, perhaps using as starting point
    # this from the default cache policies
    # https://github.com/PrefectHQ/prefect/blob/26ae72909896078d4436e4b7e90075d586347f53/src/prefect/cache_policies.py#L252

    # nested flows do not seem to work nicely with local sqlite-base server
    # this error
    # <<<ERROR>>>
    # I suspect, it's because "When a nested flow run starts, it creates a new
    # task runner for any tasks it contains.".
    # And although "Nested flow runs block execution of the parent flow run
    # until completion.", it seems it does not release the lock that the parent
    # flow has on the sqlite database and it ends up clashing with the process
    # running the nested flow. (emphasis in that I suspect, ..., I did not
    # investigate prefects' internals, but the error happens reproducibly whenever I
    # try to run a subflow, running a prefect flow locally with a sqlite-backed
    # flow).
    # Two questions:
    # - Am I right in my suspicion?, or could be something else?
    # - Is there a way to avoid this error?

    # A workaround could be, do not run a subflow, but rather use a task that
    # calls other tasks, which is one of the new features of prefect 3.0.

    # That kinda work, but then I stumbled with an issue about caching.
    # It seems the cache policy TASK_SOURCE does not recursively check for code
    # changes in subtasks (tasks called by other tasks). So, if mytask calls
    # mysubtask, and the first run cache all tasks. Then the cache policy does
    # not work when I change the code of mysubtask. Apprently it just checks
    # that the mytask source has not changed, and then loads its cache, thereby,
    # not running the task (as expected), but failing to notice that task

    #
    # quarto.render_report(strom_climate, strom_per_month, strom_per_hour)


if __name__ == "__main__":
    strom_flow()
