from prefect.tasks import task_input_hash
from prefect.filesystems import LocalFileSystem


task_ops = dict(
    cache_key_fn=task_input_hash,
    result_storage_key="{task_run.task_name}",
    result_storage=LocalFileSystem(basepath=".prefect/"),
    refresh_cache=False,
    persist_result=True,
)
