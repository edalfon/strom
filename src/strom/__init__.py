from .strom import *
from .dwd import *
from .prefect_flow import *
from .prefect_ops import *

# read version from installed package
from importlib.metadata import version

__version__ = version("strom")
