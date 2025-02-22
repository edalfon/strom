import pandas as pd
from sklearn.ensemble import RandomForestRegressor
from sklearn.linear_model import LinearRegression
from sklearn.model_selection import cross_validate
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import PolynomialFeatures
from sklego.preprocessing import ColumnSelector
from stepit import stepit

import strom


@stepit
def get_models():
    return {
        "naive": mod_naive(),
        "baseline": mod_baseline(),
        "poly": mod_poly(),
        "rf": mod_rf(),
        "rf2": mod_rf(),
        "rf44": mod_rf(),
    }


@stepit
def mod_naive():
    pipe = Pipeline(
        [
            ("vars", ColumnSelector(columns=["tt_tu_mean", "rf_tu_mean"])),
            ("model", LinearRegression()),
        ]
    )

    return pipe


@stepit
def mod_baseline():
    pipe = Pipeline(
        [
            ("vars", ColumnSelector(columns=["tt_tu_mean", "rf_tu_mean"])),
            ("polynomial", PolynomialFeatures(degree=2)),
            ("model", LinearRegression()),
        ]
    )

    return pipe


@stepit
def mod_poly():
    pipe = Pipeline(
        [
            ("vars", ColumnSelector(columns=["tt_tu_mean", "rf_tu_mean"])),
            ("polynomial", PolynomialFeatures(degree=2)),
            ("model", LinearRegression()),
        ]
    )

    return pipe


@stepit
def mod_rf():
    pipe = Pipeline(
        [
            ("vars", ColumnSelector(columns=["tt_tu_mean", "rf_tu_mean"])),
            ("model", RandomForestRegressor()),
        ]
    )

    return pipe


@stepit
def mod_rf():
    pipe = Pipeline(
        [
            ("vars", ColumnSelector(columns=["tt_tu_mean", "rf_tu_mean"])),
            ("polynomial", PolynomialFeatures(degree=2)),
            ("model", LinearRegression()),
        ]
    )

    return pipe


@stepit
def assess_model(pipe, X_train, y_train, X_test, y_test):
    pipe = pipe.fit(X_train, y_train)

    y_pred_train = pipe.predict(X_train)

    y_pred_test = pipe.predict(X_test)

    metrics_df = get_single_split_metrics(y_train, y_pred_train, y_test, y_pred_test)

    scores = cross_validate_pipe(pipe, X_train, y_train)

    scores_summ = strom.summarize_cross_validate_scores(scores)

    return pipe, y_pred_train, y_pred_test, metrics_df, scores, scores_summ


@stepit
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


@stepit
def fit_model(pipe, X_train, y_train):
    pipe.fit(X_train, y_train)

    return pipe


@stepit
def fit_predict(pipe, X_train, y_train, X_test):
    pipe = pipe.fit(X_train, y_train)

    y_pred_train = pipe.predict(X_train)

    y_pred_test = pipe.predict(X_test)

    return pipe, y_pred_train, y_pred_test


@stepit
def get_single_split_metrics(
    y_train, y_pred_train, y_test, y_pred_test, metrics_use=strom.get_metrics()
):
    metrics_train = {
        name: fn(y_train, y_pred_train) for name, fn in metrics_use.items()
    }
    metrics_test = {name: fn(y_test, y_pred_test) for name, fn in metrics_use.items()}

    metrics_df = pd.DataFrame({"train": metrics_train, "test": metrics_test})

    return metrics_df


@stepit
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
