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


def output_missing(output_dir="results", filename="01_strom_results.html"):
    # a fresh CI runner with no restored results/ cache looks just like a
    # "nothing changed" run to stepit, so fold actual output presence into
    # the cache key: only skip re-rendering when the output is really there.
    return not os.path.exists(os.path.join(output_dir, filename))


@stepit
def render_report(
    strom_climate, strom_per_month, strom_per_hour, template_hashes, output_missing
):
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
