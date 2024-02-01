from prefect import flow, task

from strom.prefect_ops import task_ops

import subprocess
import webbrowser


@task(**task_ops)
def render_report(*args, **kwargs):
    subprocess.run(["quarto", "render", "quarto", "--execute-dir", "."])
    webbrowser.open("./results/index.html")
