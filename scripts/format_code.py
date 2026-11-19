"""Apply the project's formatters to working files; never stage changes."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from check_commit import executable


def format_code(root: Path) -> None:
    commands = [
        [sys.executable, "-m", "ruff", "check", "--fix", "python", "scripts", "setup.py"],
        [sys.executable, "-m", "ruff", "format", "python", "scripts", "setup.py"],
        [executable("cargo"), "fmt", "--all"],
        [sys.executable, "-m", "miss_hit_core.mh_style", "--single", "--fix", "Matlab"],
    ]
    environment = dict(os.environ)
    for command in commands:
        subprocess.run(command, cwd=root, env=environment, check=True)
    print("Formatted working files. Review the diff and stage the changes you want to commit.")


if __name__ == "__main__":
    PROJECT_ROOT = Path(__file__).resolve().parents[1]
    format_code(PROJECT_ROOT)
