import copy
from collections.abc import Iterable, Mapping

# https://rstudio.github.io/vetiver-python/stable/reference/
# https://rstudio.github.io/pins-python/reference/
# follow-up on this issue https://github.com/rstudio/vetiver-python/issues/188
from functools import partial

import epyfun
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import pins
import plotly.graph_objects as go
from IPython.display import display
from scipy.stats import probplot
from sklearn.metrics import (
    explained_variance_score,
    make_scorer,
    mean_absolute_error,
    mean_absolute_percentage_error,
    mean_squared_error,
    median_absolute_error,
    r2_score,
)
from sklearn.model_selection import RepeatedKFold, cross_validate

import strom
import vetiver


def refit_strategy(scorer_key, agg_fn="mean"):
    def best_index(cv_results, scorer_key, agg_fn="mean"):
        cv_results = pd.DataFrame(cv_results)

        # Identify columns that match the scorer key
        scorer_cols = [
            col
            for col in cv_results.columns
            if col.endswith("test_" + scorer_key) & col.startswith("split")
        ]

        # Calculate the mean of these columns
        median_mean = cv_results[scorer_cols].mean(axis=1)
        if agg_fn == "median":
            median_mean = cv_results[scorer_cols].median(axis=1)

        index_best = median_mean.idxmax()
        if scorer_key.lower().endswith(("error", "loss", "deviance")):
            index_best = median_mean.idxmin()

        return index_best

    return partial(best_index, scorer_key=scorer_key, agg_fn=agg_fn)


from sklearn.model_selection import KFold, TimeSeriesSplit


def get_cv():
    get_kf = False
    get_rkf = False

    # cross validate, the bundled model in the pipeline
    # https://scikit-learn.org/stable/modules/cross_validation.show_html

    # using cross_val_score, that only allows you to get one scoring metric.

    # Make sure to use shuffle=True, otherwise, since the data are ordered by date and
    # we have only one year and it has a strong seasonal pattern, you would end up basically
    # we a bunch of very bad models, because january is a very bad data to predict july's
    # energy consumption

    tscv = TimeSeriesSplit(
        n_splits=5,
        # gap=7,
        max_train_size=None,
        test_size=45,
    )
    kf = KFold(n_splits=10, shuffle=True)
    rkf = RepeatedKFold(n_splits=10, n_repeats=100, random_state=7)

    # list(tscv.split(X))
    # a list with as many elements as splits
    # each element has two elements, the indices for i) training and ii) testing

    # [{"train": len(split[0]), "test": len(split[1])} for split in list(tscv.split(X))]

    if get_rkf:
        return rkf
    if get_kf:
        return kf

    return tscv


from sklearn import metrics


def get_metrics():
    metrics_use = {
        "MAE - Mean Absolute Error": metrics.mean_absolute_error,
        "MSE - Mean Squared Error": metrics.mean_squared_error,
        "RMSE - Root Mean Squared Error": metrics.root_mean_squared_error,  # np.sqrt(mse)
        "R2 - Coefficient of Determination": metrics.r2_score,
        "MAPE - Mean Absolute Percentage Error": metrics.mean_absolute_percentage_error,
        # mape = np.mean(np.abs((y_train - y_pred_train) / y_train))
        "EVS - Explained Variance Score": metrics.explained_variance_score,
        "MeAE - Median Absolute Error": metrics.median_absolute_error,
        # "log": metrics.mean_squared_log_error, # cannot be used when targets contain negative values
        "D2 - D2 Absolute Error Score": metrics.d2_absolute_error_score,
        "Pinball - Mean Pinball Loss": metrics.mean_pinball_loss,
        # "Gamma - Mean Gamma Deviance": metrics.mean_gamma_deviance,
        # # only sensitive to relative errors, but works only on positive
    }

    return metrics_use


def get_scoring():
    # scorer_names = metrics.get_scorer_names()

    scoring = {key: metrics.make_scorer(fn) for key, fn in get_metrics().items()}

    scoring = {
        key: metrics.make_scorer(
            score_func=fn,
            greater_is_better=not key.lower().endswith(("error", "loss", "deviance")),
        )
        # print(key.lower().endswith(("error", "loss", "deviance")))
        for key, fn in get_metrics().items()
    }

    return scoring


def get_board(board_path="vetiver"):
    return pins.board_folder(path=board_path, versioned=True, allow_pickle_read=True)


def log_vetiver(model, model_name, description=None, board_path="vetiver", **kwargs):
    v = vetiver.VetiverModel(
        model=model, model_name=model_name, description=description, metadata=kwargs
    )
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
    try:
        board = strom.get_board(board_path)
        vetiver_model = vetiver.VetiverModel.from_pin(
            board=board, name=model_name, version=version
        )
        return vetiver_model
    except Exception as e:
        return None
        print(f"An exception occurred: {type(e).__name__}, {e}")


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


def residuals_predicted_matplotlib(y_true, y_pred):
    residuals = y_true - y_pred

    fig, ax = plt.subplots()
    ax.scatter(y_pred, residuals)
    ax.axhline(y=0, color="r", linestyle="--")
    ax.set_xlabel("Fitted Values")
    ax.set_ylabel("Residuals")
    ax.set_title("Residuals vs Fitted Values")
    # plt.show()
    return fig


def observed_residuals_predicted(
    y_true, y_pred, data=None, dimensions=None, color=None
):
    # This is a working example of hover on subplots
    # https://plotly.com/python/hover-text-and-formatting/
    # applied to the predicted vs. observed and resuiduals vs. observed

    # plotly.__version__

    # import plotly.io as pio

    # Print the default color sequence
    # print(pio.templates["plotly"]["layout"]["colorway"])

    if data is None:
        data = pd.DataFrame()
    if dimensions is None and data is not None:
        dimensions = pd.DataFrame(data).columns.to_list()

    residuals = y_true - y_pred

    # pred_obs = go.Scatter(
    #     x=y_pred,
    #     y=y_true,
    #     xaxis="x",
    #     yaxis="y1",
    #     mode="markers",
    #     name="a",
    #     showlegend=False,
    #     marker_color="#636efa",
    #     customdata=data,
    #     hovertemplate=epyfun.make_hover_template(data),
    #     # marker_size=7,
    #     opacity=0.75,
    # )
    pred_obs = px.scatter(x=y_pred, y=y_true, color=color)
    pred_obs.update_traces(
        xaxis="x",
        yaxis="y1",
        hovertemplate=epyfun.make_hover_template(data),
        customdata=data,
    )

    # resid_obs = go.Scatter(
    #     x=y_pred,
    #     y=residuals,
    #     xaxis="x",
    #     yaxis="y2",
    #     mode="markers",
    #     name="a",
    #     showlegend=False,
    #     marker_color="#636efa",
    #     # customdata=data,
    #     hovertemplate=epyfun.make_hover_template(pd.DataFrame()),
    #     # marker_size=7,
    #     opacity=0.75,
    # )
    resid_obs = px.scatter(x=y_pred, y=residuals, color=color)
    resid_obs.update_traces(
        xaxis="x",
        yaxis="y2",
        showlegend=False,
        hovertemplate=epyfun.make_hover_template(pd.DataFrame()),
    )

    diag = go.Scatter(
        x=[min(y_true), max(y_true)],
        y=[min(y_true), max(y_true)],
        mode="lines",
        line=dict(color="red", dash="dot"),
        name="Diagonal Line",
        showlegend=False,
        xaxis="x",
        yaxis="y1",
    )

    zero = go.Scatter(
        x=[min(y_true), max(y_true)],
        y=[0, 0],
        mode="lines",
        line=dict(color="red", dash="dot"),
        name="Zero Line",
        showlegend=False,
        xaxis="x",
        yaxis="y2",
    )

    fig = go.Figure(
        data=[*pred_obs.data, *resid_obs.data, diag, zero],
        layout=dict(
            hoversubplots="axis",
            hovermode="x",
            grid=dict(rows=2, columns=1),
        ),
    )

    fig = fig.update_layout(
        autosize=True,
        height=750,
        xaxis_title="Predicted Values",
        margin=dict(l=0, r=0, t=0, b=0),
        yaxis_title="Observed Values",
        yaxis2=dict(title="Residuals"),
        # plot_bgcolor="rgba(0,0,0,0)",
        # paper_bgcolor="rgba(0,0,0,0)",
    )

    return fig


def residuals_predicted(y_true, y_pred, data=None, dimensions=None):
    fig = scatter_plotly(y_pred, y_true - y_pred, data, dimensions)

    # Add a diagonal line
    fig = fig.add_trace(
        go.Scatter(
            x=[min(y_true), max(y_true)],
            y=[0, 0],
            mode="lines",
            line=dict(color="red", dash="dot"),
            name="Zero Line",
            showlegend=False,
        )
    )

    fig = fig.update_layout(
        autosize=True,
        xaxis_title="Predicted Values",
        yaxis_title="Residuals",
        margin=dict(l=0, r=0, t=0, b=0),
        # plot_bgcolor="rgba(0,0,0,0)",
        # paper_bgcolor="rgba(0,0,0,0)",
    )

    return fig


def residuals_time(y_true, y_pred, time=None, data=None, dimensions=None):
    if time is None:
        # time = y_true.reset_index(name="time")["time"]
        time = y_true.index

    fig = scatter_plotly(time, y_true - y_pred, data, dimensions)

    # Add a diagonal line
    fig = fig.add_trace(
        go.Scatter(
            x=[min(time), max(time)],
            y=[0, 0],
            mode="lines",
            line=dict(color="red", dash="dot"),
            name="Zero Line",
            showlegend=False,
        )
    )

    fig = fig.update_xaxes(
        rangeslider_visible=True,
        rangeslider_thickness=0.1,
        rangeselector=dict(
            buttons=list(
                [
                    dict(count=15, label="15d", step="day", stepmode="backward"),
                    dict(count=1, label="1m", step="month", stepmode="backward"),
                    dict(count=6, label="6m", step="month", stepmode="backward"),
                    dict(count=1, label="YTD", step="year", stepmode="todate"),
                    dict(count=1, label="1y", step="year", stepmode="backward"),
                    dict(step="all"),
                ]
            )
        ),
    )

    fig = fig.update_layout(
        autosize=True,
        xaxis_title="Time",
        yaxis_title="Residuals",
        margin=dict(l=0, r=0, t=0, b=0),
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


def scatter_plotly(x, y, data=None, dimensions=None):
    if data is None:
        data = pd.DataFrame()
    if dimensions is None and data is not None:
        dimensions = pd.DataFrame(data).columns.to_list()

    fig = go.Figure(
        data=go.Scatter(
            x=x,
            y=y,
            mode="markers",
            marker=dict(size=10),
            opacity=0.7,
            hovertemplate=epyfun.make_hover_template(data),
            customdata=data.values,
            showlegend=False,
        )
    )

    fig = fig.update_layout(
        autosize=True,
        margin=dict(l=0, r=0, t=0, b=0),
        # plot_bgcolor="rgba(0,0,0,0)",
        # paper_bgcolor="rgba(0,0,0,0)",
    )

    return fig


def splom_fitted_observed(y_true, y_pred, data, dimensions=None):
    if dimensions is None:
        dimensions = pd.DataFrame(data).columns.to_list()

    observed_matrix = pd.concat(
        [
            pd.DataFrame({"y": y_true}).reset_index(drop=True),
            data.reset_index(drop=True),
            pd.DataFrame({"y_type": ["observed"] * len(y_true)}).reset_index(drop=True),
        ],
        axis=1,
    )

    fitted_matrix = pd.concat(
        [
            pd.DataFrame({"y": y_pred}).reset_index(drop=True),
            data.reset_index(drop=True),
            pd.DataFrame({"y_type": ["fitted"] * len(y_pred)}).reset_index(drop=True),
        ],
        axis=1,
    )

    dimensions.insert(0, "y")
    matrix_plot = pd.concat(
        [observed_matrix, fitted_matrix],
        axis=0,
        ignore_index=True,
    )
    fig = epyfun.splom(
        data_frame=matrix_plot,
        dimensions=dimensions,
        color="y_type",
        # height=700
    )

    return fig


def leverage(y_true, y_pred, pipeline, data, dimensions=None):
    residuals = y_true - y_pred

    XDM = get_design_matrix(pipeline, data).reset_index(drop=True)

    # Calculate the leverage
    # https://online.stat.psu.edu/stat501/lesson/11/11.2
    # hat = ((XDM @ np.linalg.inv(XDM.T @ XDM)) @ XDM.T)
    hat = XDM @ np.linalg.inv(XDM.T @ XDM) @ XDM.T

    hat_diag = np.diag(hat)
    leverage = hat_diag

    if dimensions is None:
        dimensions = pd.DataFrame(data).columns.to_list()

    # vector = pd.Series(
    #     [
    #         "<br>".join(f"{col}: {val}" for col, val in row.items())
    #         for _, row in data.fillna("").iterrows()
    #     ]
    # )

    fig = go.Figure(
        data=go.Scatter(
            x=leverage,
            y=residuals,
            mode="markers",
            marker=dict(size=10),
            opacity=0.7,
            # hovertext=vector,
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
        margin=dict(l=0, r=0, t=0, b=0),
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


def observed_predicted(y_true, y_pred, data=None, dimensions=None):
    fig = scatter_plotly(y_pred, y_true, data, dimensions)

    # Add a diagonal line
    fig = fig.add_trace(
        go.Scatter(
            x=[min(y_true), max(y_true)],
            y=[min(y_true), max(y_true)],
            mode="lines",
            line=dict(color="red", dash="dot"),
            name="Diagonal Line",
            showlegend=False,
        )
    )

    fig = fig.update_layout(
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
        margin=dict(l=0, r=0, t=0, b=0),
        # plot_bgcolor="rgba(0,0,0,0)",
        # paper_bgcolor="rgba(0,0,0,0)",
    )

    # fig.update_xaxes(domain=(1, 1))
    # fig.update_yaxes(domain=(1, 1))

    return fig


import plotly.express as px


# https://plotly.com/python/violin/
# https://plotly.com/python/reference/violin/
# https://plotly.com/python-api-reference/generated/plotly.express.violin.html
def plot_grid_search_results_violin(df, param_var="params", resort_xaxis=True):
    param_means = (
        df[df["set"] == "test"].groupby(param_var)["value"].mean().sort_values()
    )
    ordered_params = param_means.index.tolist()
    category_orders = {param_var: ordered_params}
    if not resort_xaxis:
        category_orders = None

    fig = px.violin(
        data_frame=df,
        x=param_var,
        y="value",
        color="set",
        color_discrete_map={"train": "orange", "test": "blue"},
        category_orders=category_orders,
        orientation="v",
        violinmode="overlay",
        points="outliers",  # "suspectedoutliers",  # all
        box=False,
        hover_name=param_var,
    )

    fig = fig.update_traces(
        # side="positive",
        width=0.95,  # 2 if horizontal and one-sided
        jitter=0.05,
        meanline_visible=True,
        scalemode="width",
        showlegend=True,
        quartilemethod="linear",  # or "inclusive", or "linear" by default
        selector=dict(type="violin"),
    )

    if resort_xaxis:
        fig = fig.update_layout(
            # xaxis=dict(visible=False),
            # https://plotly.com/python/reference/layout/xaxis/
            xaxis={
                "showticklabels": True,
                "tickmode": "array",
                "tickvals": [str(s)[:0] for s in list(ordered_params)],
                "labelalias": {
                    s: str(s)
                    .replace("{", "")
                    .replace("}", "")
                    .replace("__", " ")
                    .replace(", '", "<br>")
                    .replace("'", "")
                    for s in list(ordered_params)
                },
                # "ticklabeloverflow": "hide past div",  # "allow" | "hide past div" | hide past domain
                # "ticktext": [str(s)[:0] for s in list(ordered_params)],
                "tickangle": 0,
                "visible": True,
            },
        )

    fig = fig.update_layout(
        margin=dict(l=0, r=0, t=0, b=0),
        legend=dict(
            orientation="h",  # horizontal orientation
            yanchor="bottom",
            y=1.01,  # position slightly above the plot
            xanchor="right",
            x=0.5,
        ),
    )

    # TODO: perhaps increase transparency for training set layer
    # TODO: improve the hover, to clearly show the params, and
    #       display horizontal and not that diagonal crazy thing as default

    return fig


def plot_grid_search_results_scatter(df, scorer_col, param_var="params"):
    import plotly.express as px

    param_means = (
        df[df["set"] == "test"].groupby(param_var)[scorer_col].mean().sort_values()
    )
    ordered_params = param_means.index.tolist()

    fig = px.scatter(
        data_frame=df,
        x=param_var,
        y=scorer_col,
        color="set",
        color_discrete_map={"train": "orange", "test": "blue"},
        category_orders={param_var: ordered_params},
        hover_name=param_var,
    )

    fig = fig.update_layout(
        # xaxis=dict(visible=False),
        xaxis={
            "tickmode": "array",
            "tickvals": list(ordered_params),
            "ticktext": [str(s)[:7] for s in list(ordered_params)],
        },
        margin=dict(l=0, r=0, t=0, b=0),
        # showlegend=False,
        legend=dict(
            orientation="h",  # horizontal orientation
            yanchor="bottom",
            y=1.01,  # position slightly above the plot
            xanchor="right",
            x=0.5,
        ),
    )

    return fig


# https://scikit-learn.org/stable/modules/generated/sklearn.model_selection.GridSearchCV.html
def tidy_grid_search_results(cv_results_):
    df = pd.DataFrame(cv_results_)

    df = df.melt(
        id_vars=df.filter(like="param").columns,
        value_vars=df.filter(like="split").columns,
        var_name="colname",
    )

    df[["split", "set", "scorer"]] = df["colname"].str.split(
        "_",
        n=2,
        expand=True,
    )
    df = df.drop(columns="colname")

    mask = df["scorer"].str.lower().str.endswith(("error", "loss", "deviance"))
    df.loc[mask, "value"] *= -1

    param_vars = df.filter(like="param").columns.tolist()
    df[param_vars] = df[param_vars].astype(str)

    return df


def summarize_grid_search_results(cv_results_, agg_fn=["mean"]):
    df = tidy_grid_search_results(cv_results_)

    param_vars = df.filter(like="param").columns.tolist()

    summ_df = (
        df.groupby(param_vars + ["set", "scorer"])["value"]
        .agg(agg_fn)
        .reset_index()
        .melt(id_vars=param_vars + ["set", "scorer"], var_name="agg_fn")
    )

    df_wide = summ_df.pivot_table(
        values="value", index=param_vars + ["set", "agg_fn"], columns="scorer"
    )  # .reset_index()

    return df_wide


# TODO: perhaps do something when the grid has a refit value,
#       I don't know, give those scores a priority or something?, other color?
def plot_grid_search_results(grid_fit, param_var="params", resort_xaxis=True):
    df = tidy_grid_search_results(grid_fit.cv_results_)

    plots = {}
    if isinstance(grid_fit.scorer_, Mapping):
        for key in grid_fit.scorer_:
            df_scorer = df[df["scorer"] == key]
            fig = plot_grid_search_results_violin(df_scorer, param_var, resort_xaxis)
            fig.update_layout(yaxis_title=key)
            plots[key] = fig
    else:
        scorer_name = str(grid_fit.scorer_)
        fig = plot_grid_search_results_violin(df, param_var, resort_xaxis)
        fig.update_layout(yaxis_title=scorer_name)
        plots[scorer_name] = fig  # Wrap in dict for consistency

    return plots


def plot_grid_search_results_summary(grid_fit, param_var="params", agg_fn=["mean"]):
    df = summarize_grid_search_results(grid_fit.cv_results_, agg_fn).reset_index()

    plots = {}
    if isinstance(grid_fit.scorer_, Iterable):
        for key in grid_fit.scorer_:
            fig = plot_grid_search_results_scatter(df, key, param_var)
            fig.update_layout(yaxis_title=key)
            plots[key] = fig
    else:
        fig = plot_grid_search_results_scatter(df, key, param_var)
        fig.update_layout(yaxis_title=str(grid_fit.scorer_))
        plots = fig

    return plots


# TODO: perhaps do something when the grid has a refit value,
#       I don't know, give those scores a priority or something?, other color?
def plot_cross_validate_scores(scores, param_var="params"):
    df = tidy_cross_validate_scores(scores)

    scorers = df.scorer.unique()

    plots = {}
    for key in scorers:
        df_scorer = df[df["scorer"] == key]
        fig = plot_grid_search_results_violin(df_scorer, param_var)
        fig.update_layout(yaxis_title=key)
        plots[key] = fig

    return plots


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


def tidy_cross_validate_scores(scores, negate_loss=True):
    df = pd.DataFrame(scores)

    df = df.melt(
        # id_vars=df.filter(like="_time").columns,
        # value_vars=df.filter(regex="^train_|^test_").columns,
        # id_vars=df.columns[~df.columns.str.match("^train_|^test_")]
        id_vars=df.filter(regex="^(?!train_|test_)").columns,
        var_name="colname",
    )

    df[["set", "scorer"]] = df["colname"].str.split(
        "_",
        n=2,
        expand=True,
    )
    df = df.drop(columns="colname")

    if negate_loss:
        mask = df["scorer"].str.lower().str.endswith(("error", "loss", "deviance"))
        df.loc[mask, "value"] *= -1

    return df


def summarize_cross_validate_scores(scores, agg_fn=["mean"]):
    df = tidy_cross_validate_scores(scores)
    summ_df = df.groupby(["set", "scorer"])["value"].agg(agg_fn).reset_index()
    summ_df = summ_df.pivot(index="scorer", columns="set", values=agg_fn)

    return summ_df


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


import importlib
import inspect
import os
import sys

# from cookiecutter.main import cookiecutter


def use_project(
    package_name,
    output_dir=".",
    package_short_description="a new package. You need to add your own description at some point",
    open_source_license="MIT",
    include_github_actions="ci+cd",
):
    # Use cookiecutter programmatically
    # https://cookiecutter.readthedocs.io/en/stable/cookiecutter.html#cookiecutter.main.cookiecutter
    res_output_dir = cookiecutter(
        template="https://github.com/py-pkgs/py-pkgs-cookiecutter.git",
        no_input=True,
        extra_context={
            "author_name": "Eduardo Alfonso-Sierra",
            "package_name": package_name,
            "package_short_description": package_short_description,
            "open_source_license": open_source_license,
            "include_github_actions": include_github_actions,
        },
        output_dir=output_dir,
    )
    return res_output_dir


def reload_all():
    """Reload modules, or at least try to ...

    Uses importlib.reload to try and reload all modules currently loaded,
    identifying modules in the current scope (e.g. globals()) or those
    whose files are located within the parent directory of the current working
    directory.

    This function aims to support to use case of you are developing a package,
    try some things in a REPL, then change the code and you want those changes
    to be reflected in the REPL, without restarting it.
    Your package needs to be installed as editable (e.g. pip install -e .)

    So, if your code only import modules, this should allow you
    to reload them all without restarting or re-importing. Yet, if you used something
    `from pkg.work import fn`, it would probably reload the module pkg.work
    but not automatically the `fn`. You would need to run again the import
    command (`from pkg.work import fn`) -that's because when you import a class
    or a function using that approach, it will be an object without a reference
    to the module from which it comes from (that's why some/many? people say you should only import modules and nit directly import functions, classes or other objects). The module would probably be in sys.modules, so it will probably will be reloaded, but the class or the funcion would not be updated automatically, so you need to re-import the module that has already been reloaded-.

    :return: A list with the module names (strings) of the modules reloaded
    :rtype: list
    """

    # Reloads all Python modules whose files are located in the parent directory
    # of the current working directory.

    # Returns:
    # list: A list of module names that were successfully reloaded.

    # Note:
    # - Modules are identified by checking if their file paths start with the
    #   absolute path of the parent directory.
    # - Use with caution, as dynamic module reloading may lead to unexpected
    #   behavior, especially in the presence of global state and dependencies.

    # Save the list of module names before the reload
    modules_before_reload = set(sys.modules.keys())
    # Get the current working directory and its parent directory
    parent_directory = os.path.abspath(os.path.join(os.getcwd(), os.pardir)).lower()
    # Reload modules whose files are in the parent directory
    reloaded_modules = []
    for module_name in modules_before_reload:
        module = sys.modules.get(module_name)
        # print(module)
        if module is not None:
            try:
                module_file = os.path.abspath(getattr(module, "__file__", None)).lower()
                if module_file.startswith(parent_directory):
                    importlib.reload(module)
                    reloaded_modules.append(module_name)
            except Exception:
                None

    # This Python code snippet utilizes the inspect and importlib modules to dynamically reload all modules present in the calling frame's local variables. It identifies modules by intersecting the set of module names in the global namespace (sys.modules) with the local variables of the calling frame. For each identified module, it uses importlib.reload to refresh the module. The function returns a list of module names that were successfully reloaded. It's important to exercise caution when using dynamic module reloading, as it may lead to unexpected behavior in complex systems.

    # https://stackoverflow.com/questions/4858100/how-to-list-imported-modules
    # https://stackoverflow.com/questions/6618795/get-locals-from-calling-namespace-in-python
    frame = inspect.currentframe()
    modulenames = set(sys.modules) & set(frame.f_back.f_locals)
    allmodules = [frame.f_back.f_locals[name] for name in modulenames]
    for module in allmodules:
        try:
            importlib.reload(module)
        except Exception:
            None

    return [reloaded_modules, list(modulenames)]


def read_result(key):
    from stepit import default_deserialize

    return default_deserialize(f".stepit_cache/{key}")
