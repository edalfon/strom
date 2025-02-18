# read version from installed package
from importlib.metadata import version

# from .dwd import *
# from .prefect_flow import *
from .strom import (
    get_cv,
    get_metrics,
    get_scoring,
    read_result,
    splom_fitted_observed,
    summarize_cross_validate_scores,
)

__version__ = version("strom")

__all__ = [
    "get_metrics",
    "get_scoring",
    "get_cv",
    "summarize_cross_validate_scores",
    "read_result",
    "splom_fitted_observed",
]
