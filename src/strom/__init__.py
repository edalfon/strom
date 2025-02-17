# read version from installed package
from importlib.metadata import version

# from .dwd import *
# from .prefect_flow import *
# from .strom import *

__version__ = version("strom")
