from prefect import flow, task

from strom.prefect_ops import task_ops

import subprocess
import webbrowser

import os
import hashlib
import glob


# @task(**{**task_ops, "refresh_cache": True})
def detect_changes(folder_path="quarto", extensions=["qmd", "yml", "css"]):

    file_paths = [
        file
        for ext in extensions
        for file in glob.glob(
            os.path.join(folder_path, "**", f"*.{ext}"), recursive=True
        )
    ]
    return [hashlib.sha256(open(file, "rb").read()).hexdigest() for file in file_paths]


@task(**task_ops)
def render_report(*args, c=detect_changes(), **kwargs):
    subprocess.run(["quarto", "render", "quarto", "--execute-dir", "."])
    webbrowser.open("./results/index.html")
