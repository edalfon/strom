import json
from prefect.results import PersistedResultBlob
from prefect.serializers import JSONSerializer, PickleSerializer
from prefect.tasks import task_input_hash
from prefect.filesystems import LocalFileSystem


task_ops = dict(
    cache_key_fn=task_input_hash,
    result_storage_key="{task_run.task_name}",
    result_storage=LocalFileSystem(basepath=".prefect/"),
    refresh_cache=False,
    persist_result=True,
)


def read_result(
    filename: str, storage=task_ops["result_storage"], serialier: str = "pickle"
):
    path = storage._resolve_path(filename)
    with open(path, "rb") as buffered_reader:
        dict_obj = json.load(buffered_reader)
        blob = PersistedResultBlob.parse_obj(dict_obj)
    if serialier == "json":
        result = JSONSerializer().loads(blob.data)
    else:
        result = PickleSerializer().loads(blob.data)
    return result
