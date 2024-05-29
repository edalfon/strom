from prefect import flow, task

from strom.prefect_ops import task_ops

import subprocess
import webbrowser

import os
import hashlib
import glob


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
def render_report(*args, changes=True, **kwargs):
    cmd = ["quarto", "render", "quarto", "--execute-dir", "."]
    if changes:
        cmd.append("--metadata")
        cmd.append("freeze:false")

    subprocess.run(cmd)

    webbrowser.open("./results/index.html")
