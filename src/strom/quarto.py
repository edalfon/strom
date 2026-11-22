import glob
import hashlib
import os
import subprocess
import webbrowser

from stepit import stepit


def detect_changes(
    folder_path="quarto",
    extensions=["qmd", "yml", "css"],
    code_path=os.path.dirname(__file__),
):
    """Hashes of the site's sources, so that render_report re-runs when they change.

    Besides the Quarto files, this includes the package's own Python code
    (`code_path`), because the pages call into it (e.g. the chart helpers in
    strom.echarts): a change there must re-render the site too.
    """
    file_paths = [
        file
        for ext in extensions
        for file in glob.glob(
            os.path.join(folder_path, "**", f"*.{ext}"), recursive=True
        )
    ]
    if code_path:
        file_paths += glob.glob(os.path.join(code_path, "*.py"))
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

    # tell the CI step that a render actually happened this run, so it can
    # skip steps (html print, Pages deploy) that only make sense after one.
    # a no-op locally, where GITHUB_OUTPUT isn't set.
    github_output = os.environ.get("GITHUB_OUTPUT")
    if github_output:
        with open(github_output, "a") as f:
            f.write("rendered=true\n")

    webbrowser.open("./results/index.html")
