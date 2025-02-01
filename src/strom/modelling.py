from prefect import flow, task, get_run_logger
from sklearn.preprocessing import PolynomialFeatures

from strom.prefect_ops import task_ops

from strom import meter, dwd, consumption, quarto

import pandas as pd

from datetime import date

import epyfun

import strom

from sklearn import metrics
from sklearn.model_selection import cross_validate

from sklearn.pipeline import Pipeline
from sklearn.linear_model import LinearRegression

from sklego.preprocessing import ColumnSelector


@task(**task_ops)
def get_models():

    return {"naive": mod_naive(), "baseline": mod_baseline()}


@task(**task_ops)
def mod_naive():

    pipe = Pipeline(
        [
            ("vars", ColumnSelector(columns=["tt_tu_mean", "rf_tu_mean"])),
            ("model", LinearRegression()),
        ]
    )

    return pipe


@task(**task_ops)
def mod_baseline():

    pipe = Pipeline(
        [
            ("vars", ColumnSelector(columns=["tt_tu_mean", "rf_tu_mean"])),
            ("polynomial", PolynomialFeatures(degree=2)),
            ("model", LinearRegression()),
        ]
    )

    return pipe


@task(**task_ops)
def assess_model(pipe, X_train, y_train, X_test, y_test):

    pipe, y_pred_train, y_pred_test = fit_predict(pipe, X_train, y_train, X_test)

    metrics_df = get_single_split_metrics(y_train, y_pred_train, y_test, y_pred_test)

    return metrics_df


@task(**task_ops)
def split_data(strom_climate, cutoff="2023-12-05"):

    # cutoff = strom_climate["date"].max() - pd.DateOffset(years=1)

    strom_climate["ds"] = strom_climate["date"].dt.date
    strom_climate = strom_climate.set_index("ds")

    train_set = strom_climate[strom_climate["date"] <= cutoff]
    test_set = strom_climate[strom_climate["date"] > cutoff]

    X_train = train_set.drop(columns="wd")
    y_train = train_set["wd"]
    X_test = test_set.drop(columns="wd")
    y_test = test_set["wd"]

    return X_train, y_train, X_test, y_test


@task(**task_ops)
def fit_predict(pipe, X_train, y_train, X_test):
    pipe.fit(X_train, y_train)

    y_pred_train = pipe.predict(X_train)

    y_pred_test = pipe.predict(X_test)

    return pipe, y_pred_train, y_pred_test


@task(**task_ops)
def get_single_split_metrics(
    y_train, y_pred_train, y_test, y_pred_test, metrics_use=strom.get_metrics()
):

    metrics_train = {
        name: fn(y_train, y_pred_train) for name, fn in metrics_use.items()
    }
    metrics_test = {name: fn(y_test, y_pred_test) for name, fn in metrics_use.items()}

    metrics_df = pd.DataFrame({"train": metrics_train, "test": metrics_test})

    return metrics_df


@task(**task_ops)
def cross_validate_pipe(
    pipe, X_train, y_train, scoring=strom.get_scoring(), cv=strom.get_cv()
):

    scores = cross_validate(
        pipe,
        X_train,
        y_train,
        scoring=scoring,
        cv=cv,
        n_jobs=-1,
        verbose=1,
        return_train_score=True,
    )

    return scores
