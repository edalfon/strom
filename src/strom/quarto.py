import glob
import hashlib
import os
import subprocess
import webbrowser

from stepit import stepit


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
        for file in sorted(file_paths)
    }

    return hashes


@stepit
def render_report(strom_climate, strom_per_month, strom_per_hour, template_hashes):
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
