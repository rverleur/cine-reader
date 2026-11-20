"""Test wheel, checkout and available sdist installs with only Python packages on PATH."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from release import (
    ROOT,
    binary_module,
    clean_environment,
    source_snapshot,
    verify_sdist,
    verify_wheel,
)


def check_installations(root: Path, distributions: Path, reports: Path) -> None:
    binary = binary_module(root)
    target = binary.host_target()
    wheels = [wheel for wheel in distributions.glob("*.whl") if verify_wheel(root, wheel) == target]
    if len(wheels) != 1:
        raise ValueError("Expected exactly one verified wheel matching this host.")
    sdists = list(distributions.glob("*.tar.gz"))
    if len(sdists) > 1:
        raise ValueError("Expected at most one source archive.")
    for sdist in sdists:
        verify_sdist(root, sdist)
    reports.mkdir(parents=True, exist_ok=True)
    environment = clean_environment()
    with tempfile.TemporaryDirectory(prefix="cine-python-only-") as temporary:
        work = Path(temporary)
        wheelhouse = work / "dependencies"
        wheelhouse.mkdir()
        with (reports / "dependencies.log").open("w", encoding="utf-8") as log:
            subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "pip",
                    "download",
                    "--only-binary=:all:",
                    "--dest",
                    str(wheelhouse),
                    "numpy>=1.24",
                    "Pillow>=9",
                    "av>=12",
                    "pytest>=8",
                    "setuptools>=77.0.3",
                    "wheel",
                ],
                env=environment,
                stdout=log,
                stderr=subprocess.STDOUT,
                check=True,
            )
        checkout = work / "checkout"
        source_snapshot(root, checkout)
        tests = work / "tests"
        shutil.copytree(root / "python/tests", tests, ignore=shutil.ignore_patterns("__pycache__"))
        shutil.copy2(root / "pytest.ini", work / "pytest.ini")
        library, manifest = binary.select_prebuilt(root)
        digest = manifest["artifacts"][library.name]["sha256"]
        probe = work / "installed_probe.py"
        probe.write_text(
            "import hashlib, sys\n"
            "from pathlib import Path\n"
            "import cine_reader\n"
            "from cine_reader._native import library\n"
            "package = Path(cine_reader.__file__).resolve()\n"
            "native = Path(library()._name).resolve()\n"
            "assert package.is_relative_to(Path(sys.prefix).resolve()), package\n"
            "assert native.is_relative_to(Path(sys.prefix).resolve()), native\n"
            f"assert hashlib.sha256(native.read_bytes()).hexdigest() == {digest!r}\n"
            "print('Verified installed package:', package)\n"
            "print('Verified installed backend:', native)\n",
            encoding="utf-8",
        )
        installs = [("wheel", wheels[0]), ("checkout", checkout)]
        installs.extend(("sdist", path) for path in sdists)
        for label, source in installs:
            virtualenv = work / f"venv-{label}"
            subprocess.run(
                [sys.executable, "-m", "venv", str(virtualenv)], env=environment, check=True
            )
            python = virtualenv / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
            restricted = dict(
                environment, PATH="", PIP_NO_INDEX="1", PIP_FIND_LINKS=str(wheelhouse)
            )
            with (reports / f"{label}.log").open("w", encoding="utf-8") as log:
                for command in (
                    [str(python), "-m", "pip", "install", f"{source}[media]", "pytest>=8"],
                    [str(python), str(probe)],
                    [str(python), "-m", "pytest", str(tests), "-q", "-rs"],
                ):
                    subprocess.run(
                        command,
                        cwd=work,
                        env=restricted,
                        stdout=log,
                        stderr=subprocess.STDOUT,
                        check=True,
                    )
            print(
                f"Python-only {label} installation and runtime tests passed; {reports / (label + '.log')}"
            )


if __name__ == "__main__":
    # Configure these paths here for an IDE run, or use the equivalent CI environment variables.
    DISTRIBUTIONS = Path(
        os.environ.get("CINE_RELEASE_OUTPUT", str(ROOT / "dist/release"))
    ).resolve()
    REPORTS = Path(
        os.environ.get("CINE_RELEASE_REPORTS", str(ROOT / "dist/release-checks"))
    ).resolve()
    check_installations(ROOT, DISTRIBUTIONS, REPORTS)
