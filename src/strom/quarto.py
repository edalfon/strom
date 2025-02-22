import glob
import hashlib
import os
import subprocess
import webbrowser


def detect_changes(folder_path="quarto", extensions=["qmd", "yml", "css"]):
    file_paths = [
        file
        for ext in extensions
        for file in glob.glob(
            os.path.join(folder_path, "**", f"*.{ext}"), recursive=True
        )
    ]
    hashes = {
        f"{file}": hashlib.sha256(open(file, "rb").read()).hexdigest()
        for file in file_paths
    }
    print(hashes)
    return hashes


def render_report(*args, changes=detect_changes(), **kwargs):
    cmd = [
        "quarto",
        "render",
        "quarto",
        "--execute-dir",
        ".",
        "--metadata",
        "freeze:false",
    ]

    subprocess.run(cmd)

    webbrowser.open("./results/index.html")
