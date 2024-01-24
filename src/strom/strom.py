import vetiver
import pins

import pandas as pd

from sklearn.metrics import (
    PredictionErrorDisplay,
    make_scorer,
    mean_absolute_error,
    mean_absolute_percentage_error,
    mean_squared_error,
    median_absolute_error,
    r2_score,
    explained_variance_score,
)
import numpy as np
from scipy.stats import probplot
import matplotlib.pyplot as plt

import copy

import plotly.graph_objects as go

import strom
import epyfun

from sklearn.model_selection import cross_validate
from sklearn.model_selection import RepeatedKFold

from IPython.display import display, Markdown

# https://rstudio.github.io/vetiver-python/stable/reference/
# https://rstudio.github.io/pins-python/reference/

# follow-up on this issue https://github.com/rstudio/vetiver-python/issues/188


def get_board(board_path="vetiver"):
    return pins.board_folder(path=board_path, versioned=True, allow_pickle_read=True)


def log_vetiver(model, model_name, board_path="vetiver", **kwargs):
    v = vetiver.VetiverModel(model=model, model_name=model_name, **kwargs)
    vetiver.vetiver_pin_write(
        board=strom.get_board(board_path), model=v, versioned=True
    )
    strom.prune_duplicates(model_name, board_path)
    return v


def prune_duplicates(model_name, board_path="vetiver"):
    model_versions = strom.get_board().pin_versions(name=model_name)

    # we want to keep only the latest version per hash
    idx_to_exclude = model_versions.groupby("hash")["created"].idxmax()
    versions_to_prune = model_versions.drop(idx_to_exclude)

    # iterate and delete old versions with the same hash
    # TODO: I do not think pin_version_delete() is vectorized, but doble-check
    for index, row in versions_to_prune.iterrows():
        strom.get_board(board_path).pin_version_delete(
            name=model_name, version=row["version"]
        )


def get_vetiver(model_name, version=None, board_path="vetiver"):
    board = strom.get_board(board_path)
    vetiver_model = vetiver.VetiverModel.from_pin(
        board=board, name=model_name, version=version
    )
    return vetiver_model


def assess_vetiver_regression(
    vetiver_model,
    input_data,
    y_true,
    metric_set=[
        mean_squared_error,
        mean_absolute_error,
        r2_score,
        explained_variance_score,
    ],
    **kw,
):
    print("input_data: ", input_data)
    y_pred = vetiver_model.handler_predict(input_data=input_data, check_prototype=False)
    y_pred = pd.Series(y_pred)

    if isinstance(y_true, str) and y_true in input_data.columns:
        y_true = input_data[y_true]

    missing_values = y_pred.isnull() | y_true.isnull()

    # Remove observations where either of the Series has missing values
    y_pred = y_pred[~missing_values]
    y_true = y_true[~missing_values]

    # that's how they do it in compute_metrics()
    # https://github.com/rstudio/vetiver-python/blob/ffadf81d362ab90d487908d93e39a9b5548ce624/vetiver/monitor.py
    rows = []
    for m in metric_set:
        rows = rows + [
            {
                "metric": m.__qualname__,
                "estimate": m(y_pred=y_pred, y_true=y_true, **kw),
            }
        ]

    outdf = pd.DataFrame.from_dict(rows)

    return outdf


def residuals_fitted_matplotlib(y_true, y_pred):
    residuals = y_true - y_pred

    fig, ax = plt.subplots()
    ax.scatter(y_pred, residuals)
    ax.axhline(y=0, color="r", linestyle="--")
    ax.set_xlabel("Fitted Values")
    ax.set_ylabel("Residuals")
    ax.set_title("Residuals vs Fitted Values")
    # plt.show()
    return fig


def residuals_fitted(y_true, y_pred, data=None, dimensions=None):
    residuals = y_true - y_pred

    if data is None:
        data = pd.DataFrame()
    if dimensions is None and data is not None:
        dimensions = pd.DataFrame(data).columns

    # plot_matrix = pd.concat(
    #     [pd.DataFrame({"y": y_true}), pd.DataFrame({"y": y_pred}), data],
    #     axis=1,
    # )

    fig = go.Figure(
        data=go.Scatter(
            x=y_pred,
            y=y_true - y_pred,
            mode="markers",
            marker=dict(size=10),
            opacity=0.7,
            hovertemplate=epyfun.make_hover_template(data),
            customdata=data.values,
            showlegend=False,
        )
    )

    # Add a diagonal line
    fig.add_trace(
        go.Scatter(
            x=[min(y_true), max(y_true)],
            y=[0, 0],
            mode="lines",
            line=dict(color="red", dash="dot"),
            name="Zero Line",
            showlegend=False,
        )
    )

    fig.update_layout(
        autosize=True,
        xaxis_title="Predicted Values",
        yaxis_title="Residuals",
        margin=dict(l=0, r=0, t=0, b=0)
        # plot_bgcolor="rgba(0,0,0,0)",
        # paper_bgcolor="rgba(0,0,0,0)",
    )

    return fig


def residuals_hist(y_true, y_pred, **kwargs):
    residuals = y_true - y_pred

    fig, ax = plt.subplots()
    ax.hist(residuals, **kwargs)
    ax.set_xlabel("Residuals")
    ax.set_ylabel("Frequency")
    ax.set_title("Histogram of Residuals")
    # plt.show()
    return fig


def residuals_qq(y_true, y_pred, **kwargs):
    residuals = y_true - y_pred

    # or using statsmodels, much shorter
    # QQ plot for normality
    # sm.qqplot(residuals, line='s')
    fig, ax = plt.subplots()
    probplot(residuals, dist="norm", plot=ax)
    ax.set_xlabel("Theoretical Quantiles")
    ax.set_ylabel("Sample Quantiles")
    ax.set_title("Quantile-Quantile Plot")
    # plt.show()
    return fig


def splom_fitted_observed(y_true, y_pred, data, dimensions=None):
    if dimensions is None:
        dimensions = pd.DataFrame(data).columns

    observed_matrix = pd.concat(
        [
            pd.DataFrame({"y": y_true}),
            data,
            pd.DataFrame({"y_type": ["observed"] * len(y_true)}),
        ],
        axis=1,
    )

    fitted_matrix = pd.concat(
        [
            pd.DataFrame({"y": y_pred}),
            data,
            pd.DataFrame({"y_type": ["fitted"] * len(y_pred)}),
        ],
        axis=1,
    )

    dimensions.insert(0, "y")
    matrix_plot = pd.concat([observed_matrix, fitted_matrix], axis=0, ignore_index=True)
    fig = epyfun.splom(
        data_frame=matrix_plot, dimensions=dimensions, color="y_type", height=700
    )

    return fig


def leverage(y_true, y_pred, pipeline, data, dimensions=None):
    residuals = y_true - y_pred

    XDM = get_design_matrix(pipeline, data)

    # Calculate the leverage
    hat = XDM @ np.linalg.inv(XDM.T @ XDM) @ XDM.T
    hat_diag = np.diag(hat)
    leverage = hat_diag

    if data is None:
        data = pd.DataFrame()
    if dimensions is None and data is not None:
        dimensions = pd.DataFrame(data).columns

    vector = pd.Series(
        [
            "<br>".join(f"{col}: {val}" for col, val in row.items())
            for _, row in data.fillna("").iterrows()
        ]
    )

    fig = go.Figure(
        data=go.Scatter(
            x=leverage,
            y=residuals,
            mode="markers",
            marker=dict(size=10),
            opacity=0.7,
            hovertext=vector,
            hoverinfo="text",
            hovertemplate=epyfun.make_hover_template(data),
            customdata=data,
            showlegend=False,
        )
    )

    # fig.add_trace(
    #     go.Scatter(
    #         x=[min(y_true), max(y_true)],
    #         y=[min(y_true), max(y_true)],
    #         mode="lines",
    #         line=dict(color="red", dash="dot"),
    #         name="Diagonal Line",
    #         showlegend=False,
    #     )
    # )

    fig.update_layout(
        autosize=True,
        # xaxis=dict(
        #     scaleanchor="y",
        #     scaleratio=1,
        # ),
        # yaxis=dict(
        #     scaleanchor="x",
        #     scaleratio=1,
        # ),
        # width=700,
        # height=700,
        xaxis_title="Leverage",
        yaxis_title="Residuals",
        margin=dict(l=0, r=0, t=0, b=0)
        # plot_bgcolor="rgba(0,0,0,0)",
        # paper_bgcolor="rgba(0,0,0,0)",
    )
    fig.update_xaxes(showspikes=True)
    fig.update_yaxes(showspikes=True)
    # fig.update_layout(hoverlabel=dict(bgcolor="white", font_size=2))

    # import plotly.express as px

    # df_2007 = px.data.gapminder().query("year==2007")
    # df_2007 = df_2007.assign(**{f"{col}_dup1": df_2007[col] for col in df_2007.columns})
    # df_2007 = df_2007.assign(**{f"{col}_dup2": df_2007[col] for col in df_2007.columns})
    # df_2007 = df_2007.assign(**{f'{col}_dup3': df_2007[col] for col in df_2007.columns})

    # fig = px.scatter(
    #     df_2007,
    #     x="gdpPercap",
    #     y="lifeExp",
    #     log_x=True,
    #     hover_name="country",
    #     hover_data=df_2007.columns,
    # )
    # fig.update_layout(hoverlabel=dict(font_size=8))

    # fig.show()

    # fig.update_xaxes(domain=(1, 1))
    # fig.update_yaxes(domain=(1, 1))

    return fig

    # fig, ax = plt.subplots()
    # ax.scatter(leverage, residuals)
    # ax.set_xlabel("Leverage")
    # ax.set_ylabel("Leverage")
    # ax.set_title("Residuals vs Leverage")
    # # plt.show()
    # return fig


def get_design_matrix(pipeline, X_input):
    # To get the design matrix for a given pipeline, we want to take advantage
    # of the method transform(), that "also works where final estimator is None
    # in which case all prior transformations are applied". So we basically want
    # to replace the last estimator which is typically a model with None, and then
    # apply transform() to obtain the design matrix (so all the transformed data
    # that would be fed into the model). But to do that we need to use set_params()
    # that modifies the pipeline in place. Therefore, we need to create a deep copy
    # of the pipeline to avoid modifying the oriignal object
    # https://scikit-learn.org/stable/modules/generated/sklearn.pipeline.Pipeline.html#sklearn.pipeline.Pipeline.set_params
    pipeline_copy = copy.deepcopy(pipeline)

    # Get the name of the last estimator in the pipeline, by indexing the
    # last element of the list and then the first element of the tuple
    last_estimator_name = pipeline_copy.steps[-1][0]

    # and replace the last estimator with None
    pipeline_copy.set_params(**{last_estimator_name: None})

    # Transform X using the copy
    design_matrix = pipeline_copy.transform(X_input)
    return design_matrix


# Scale-Location plot shows whether residuals are spread equally along the ranges of input variables (predictor). The assumption of equal variance (homoscedasticity) could also be checked with this plot. If we see a horizontal line with randomly spread points, it means that the model is good.
# Scale-Location It’s also called a Spread-Location plot. This plot shows if residuals are spread equally along the ranges of predictors. This is how you can check the assumption of equal variance (homoscedasticity). It’s good if you see a horizontal line with equally (randomly) spread points.
def scale_location(y_true, y_pred, pipeline, data):
    residuals = y_true - y_pred

    model_norm_residuals_abs_sqrt = np.sqrt(np.abs(residuals))

    residuals = y_true - y_pred

    fig, ax = plt.subplots()
    ax.scatter(y_pred, model_norm_residuals_abs_sqrt)
    ax.set_xlabel("Fitted Values")
    ax.set_ylabel("Sqrt(|Standardized Residuals|)")
    ax.set_title("Scale-Location Plot")
    # plt.show()
    return fig


def scatter_fitted_observed(y_true, y_pred, data=None, dimensions=None):
    if data is None:
        data = pd.DataFrame()
    if dimensions is None and data is not None:
        dimensions = pd.DataFrame(data).columns

    # plot_matrix = pd.concat(
    #     [pd.DataFrame({"y": y_true}), pd.DataFrame({"y": y_pred}), data],
    #     axis=1,
    # )

    fig = go.Figure(
        data=go.Scatter(
            x=y_pred,
            y=y_true,
            mode="markers",
            marker=dict(size=10),
            opacity=0.7,
            hovertemplate=epyfun.make_hover_template(data),
            customdata=data.values,
            showlegend=False,
        )
    )

    # Add a diagonal line
    fig.add_trace(
        go.Scatter(
            x=[min(y_true), max(y_true)],
            y=[min(y_true), max(y_true)],
            mode="lines",
            line=dict(color="red", dash="dot"),
            name="Diagonal Line",
            showlegend=False,
        )
    )

    fig.update_layout(
        autosize=True,
        # xaxis=dict(
        #     scaleanchor="y",
        #     scaleratio=1,
        # ),
        # yaxis=dict(
        #     scaleanchor="x",
        #     scaleratio=1,
        # ),
        # width=700,
        # height=700,
        xaxis_title="Predicted Values",
        yaxis_title="Observed Values",
        margin=dict(l=0, r=0, t=0, b=0)
        # plot_bgcolor="rgba(0,0,0,0)",
        # paper_bgcolor="rgba(0,0,0,0)",
    )

    # fig.update_xaxes(domain=(1, 1))
    # fig.update_yaxes(domain=(1, 1))

    return fig


def get_model_data():
    strom_climate = pd.read_parquet("interim/strom_climate.parquet")
    X = strom_climate.drop(columns="wd")
    y = strom_climate["wd"]

    return X, y


def cross_validate_strom(estimator, X, y):
    rkf = RepeatedKFold(n_splits=10, n_repeats=100, random_state=7)

    scoring = {
        "R2": "r2",
        "ExVar": "explained_variance",
        "MAE": make_scorer(mean_absolute_error),
        "MAPE": make_scorer(mean_absolute_percentage_error),
        "MeAE": make_scorer(median_absolute_error),
        "MSE": make_scorer(mean_squared_error),
    }

    scores = cross_validate(
        estimator,
        X,
        y,
        scoring=scoring,
        cv=rkf,
        n_jobs=-1,
        verbose=0,
        return_train_score=True,
    )

    return scores


def assess_regression(estimator, X, y, dimensions=None):
    y_pred = estimator.predict(X)

    scores = strom.cross_validate_strom(estimator, X, y)
    scores_df = strom.summarize_cross_validate_scores(scores)
    display(scores_df)

    p1 = strom.scatter_fitted_observed(y, y_pred, X, dimensions).show()

    p2 = strom.residuals_fitted(y, y_pred, X, dimensions).show()
    p3 = strom.splom_fitted_observed(y, y_pred, X, dimensions).show()
    p4 = strom.residuals_hist(y, y_pred)
    p5 = strom.residuals_qq(y, y_pred)
    p6 = strom.leverage(y, y_pred, estimator, X).show()
    p7 = strom.scale_location(y, y_pred, estimator, X)

    return {"x1": scores_df, "x2": p1, "x2": p3, "x2": p4, "x2": p5, "x2": p6, "x2": p7}


def summarize_cross_validate_scores(scores):
    scores_df = pd.DataFrame(scores)

    # Drop columns that end with '_time'
    scores_df = scores_df.drop(columns=["fit_time", "score_time"])

    # Reshape the DataFrame
    scores_df = scores_df.melt(var_name="colname")
    scores_df[["traintest", "metric"]] = scores_df["colname"].str.split(
        "_", n=1, expand=True
    )
    scores_df = scores_df.drop(columns="colname")

    # Aggregate by calculating the mean for each metric in the test and train sets
    scores_df = scores_df.groupby(["traintest", "metric"]).mean().reset_index()
    # Reshape the DataFrame again
    scores_df = scores_df.pivot(index="metric", columns="traintest", values="value")

    return scores_df


# {python}
# from sklearn.metrics import PredictionErrorDisplay
# import matplotlib.pyplot as plt

# fig, axs = plt.subplots(ncols=2, figsize=(8, 4))
# PredictionErrorDisplay.from_predictions(
#     y,
#     y_pred=y_pred,
#     kind="actual_vs_predicted",
#     #subsample=100,
#     ax=axs[0],
#     random_state=0,
# )
# axs[0].set_title("Actual vs. Predicted values")
# PredictionErrorDisplay.from_predictions(
#     y,
#     y_pred=y_pred,
#     kind="residual_vs_predicted",
#     #subsample=100,
#     ax=axs[1],
#     random_state=0,
# )
# axs[1].set_title("Residuals vs. Predicted Values")
# fig.suptitle("Plotting cross-validated predictions")
# plt.tight_layout()
# plt.show()
# ```
