"""Install repository-local commit gates. Run once for each clone from its venv."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from check_commit import CheckFailure, configuration, executable


def install_hooks(
    root: Path, *, python: str, matlab: str | None = None, corpus: str | None = None
) -> None:
    # Never silently replace another project's hook manager.
    existing = subprocess.run(
        ["git", "-C", str(root), "config", "--get", "core.hooksPath"],
        capture_output=True,
        text=True,
        check=False,
    )
    if existing.returncode not in (0, 1):
        raise CheckFailure("Cannot inspect the existing Git hooks configuration.")
    if existing.stdout.strip() not in ("", ".githooks", str(root / ".githooks")):
        raise CheckFailure(
            f"An existing hooks directory is configured: {existing.stdout.strip()}. Integrate it before replacing it."
        )
    if not existing.stdout.strip():
        hooks = subprocess.check_output(
            ["git", "-C", str(root), "rev-parse", "--git-path", "hooks"], text=True
        ).strip()
        directory = Path(hooks)
        if not directory.is_absolute():
            directory = root / directory
        if any(
            (directory / name).is_file()
            for name in ("pre-commit", "pre-merge-commit", "pre-applypatch")
        ):
            raise CheckFailure(
                f"Existing commit hooks found in {directory}. Integrate them before installing this gate."
            )
    matlab = executable("matlab", matlab or configuration(root, "cine.matlab"))
    executable("cargo")
    executable("ffmpeg")
    executable("ffprobe")
    for name in ("pre-commit", "pre-merge-commit", "pre-applypatch"):
        hook = root / ".githooks" / name
        if not hook.is_file():
            raise CheckFailure(f"Missing hook: {hook}")
        hook.chmod(hook.stat().st_mode | 0o111)
    settings = {
        "core.hooksPath": ".githooks",
        "cine.python": str(Path(python).absolute()),
        "cine.matlab": matlab,
    }
    if corpus is not None:
        directory = Path(corpus).expanduser().resolve()
        if not directory.is_dir():
            raise CheckFailure(f"Corpus directory does not exist: {directory}")
        settings["cine.testCorpus"] = str(directory)
    for key, value in settings.items():
        subprocess.run(["git", "-C", str(root), "config", "--local", key, value], check=True)
    print("Installed commit, merge-commit and apply-patch gates for this clone.")
    print("Run scripts/format_code.py, review/stage changes, then commit normally.")


if __name__ == "__main__":
    PROJECT_ROOT = Path(__file__).resolve().parents[1]
    PYTHON = sys.executable
    MATLAB = None  # Auto-discover, or set the full path to the MATLAB executable.
    CORPUS = None  # Optional directory containing the 14 reference camera files.
    install_hooks(PROJECT_ROOT, python=PYTHON, matlab=MATLAB, corpus=CORPUS)
