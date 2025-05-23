# read version from installed package
from importlib.metadata import version

# from . import consumption, duckdb, dwd, meter, modelling
from .strom import (
    assess_regression,
    assess_vetiver_regression,
    cross_validate_strom,
    get_board,
    get_cv,
    get_metrics,
    get_scoring,
    get_vetiver,
    leverage,
    log_vetiver,
    observed_predicted,
    observed_residuals_predicted,
    plot_cross_validate_scores,
    plot_grid_search_results,
    plot_grid_search_results_scatter,
    plot_grid_search_results_summary,
    plot_grid_search_results_violin,
    prune_duplicates,
    read_result,
    refit_strategy,
    reload_all,
    residuals_hist,
    residuals_predicted,
    residuals_predicted_matplotlib,
    residuals_qq,
    residuals_time,
    scale_location,
    scatter_plotly,
    splom_fitted_observed,
    summarize_cross_validate_scores,
    summarize_grid_search_results,
    tidy_cross_validate_scores,
    tidy_grid_search_results,
    use_project,
)

__version__ = version("strom")

__all__ = [
    # consumption functions
    "calculate_avg_consumption",
    "calculate_avg_consumption_periods",
    "compare_last_days",
    "get_period",
    "get_period_cummulative",
    "normalstrom_consumption",
    "waermestrom_consumption",
    # modelling functions
    "assess_model",
    "cross_validate_pipe",
    "fit_model",
    "fit_predict",
    "get_models",
    "get_single_split_metrics",
    "mod_baseline",
    "mod_naive",
    "mod_poly",
    "mod_rf",
    "split_data",
    # strom functions
    "assess_regression",
    "assess_vetiver_regression",
    "cross_validate_strom",
    "get_board",
    "get_cv",
    "get_metrics",
    "get_scoring",
    "get_vetiver",
    "leverage",
    "log_vetiver",
    "observed_predicted",
    "observed_residuals_predicted",
    "plot_cross_validate_scores",
    "plot_grid_search_results",
    "plot_grid_search_results_scatter",
    "plot_grid_search_results_summary",
    "plot_grid_search_results_violin",
    "prune_duplicates",
    "read_result",
    "refit_strategy",
    "reload_all",
    "residuals_hist",
    "residuals_predicted",
    "residuals_predicted_matplotlib",
    "residuals_qq",
    "residuals_time",
    "scale_location",
    "scatter_plotly",
    "splom_fitted_observed",
    "summarize_cross_validate_scores",
    "summarize_grid_search_results",
    "tidy_cross_validate_scores",
    "tidy_grid_search_results",
    "use_project",
]
