from prefect.cache_policies import INPUTS, TASK_SOURCE

from prefect.results import ResultStore
from prefect.filesystems import LocalFileSystem

# TODO: customize here the local file system, to not rely on server
#       level config
task_ops = dict(
    cache_policy=INPUTS + TASK_SOURCE,
    result_storage_key="{task_run.task_name}",
    # result_storage=LocalFileSystem(basepath=".prefect"),
    # result_storage=".prefect",
    # refresh_cache=True,
    persist_result=True,
)


# TODO: robust way to get ResultStore, possibly customized
def read_result(filename: str, storage=None):
    # rr1.metadata
    return ResultStore().read(filename).result
