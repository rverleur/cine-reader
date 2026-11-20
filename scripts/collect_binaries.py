"""Build and collect native distributables. Configure IDE options in __main__."""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from build_native import build_native
from check_commit import configuration, executable

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "cine_binary_collect", ROOT / "python/src/cine_reader/_binary.py"
)
binary = importlib.util.module_from_spec(spec)
spec.loader.exec_module(binary)

MATLAB_TARGETS = {
    "aarch64-apple-darwin": ("maca64", "mexmaca64"),
    "x86_64-apple-darwin": ("maci64", "mexmaci64"),
    "x86_64-pc-windows-msvc": ("win64", "mexw64"),
    "x86_64-unknown-linux-gnu": ("glnxa64", "mexa64"),
}


def source_status() -> str:
    return subprocess.check_output(
        [
            "git",
            "status",
            "--porcelain",
            "--untracked-files=all",
            "--",
            ".",
            ":(exclude)binaries",
        ],
        cwd=ROOT,
        text=True,
    )


def collect_binaries(*, include_matlab: bool = True) -> Path:
    """Collect one native target; all source edits must be committed first."""
    status = source_status()
    if status.strip():
        raise RuntimeError("Commit source changes before collecting binaries:\n" + status)
    binary.check_build_environment(ROOT)
    target = binary.host_target()
    if include_matlab and target not in MATLAB_TARGETS:
        raise RuntimeError(
            f"MATLAB gateways are not supported for {target}; set INCLUDE_MATLAB=False."
        )
    cargo, rustc = executable("cargo"), executable("rustc")
    rustc_version = subprocess.check_output([rustc, "-vV"], text=True).strip()
    if f"host: {target}" not in rustc_version.splitlines():
        raise RuntimeError(
            "Rust's host toolchain must match this Python process and operating system."
        )
    matlab = None
    if include_matlab:
        matlab = executable("matlab", configuration(ROOT, "cine.matlab"))
    if sys.platform == "darwin":
        os.environ.setdefault("MACOSX_DEPLOYMENT_TARGET", "11.0")
    source_commit = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
    ).strip()
    before = binary.source_fingerprint(ROOT)
    build_native(release=True)
    subprocess.run([cargo, "test", "--workspace", "--locked"], cwd=ROOT, check=True)
    target_dir = Path(os.environ.get("CARGO_TARGET_DIR", str(ROOT / "target")))
    if not target_dir.is_absolute():
        target_dir = ROOT / target_dir
    output = target_dir.resolve() / "release"
    library = output / binary.library_name(target)
    cli = output / ("cine-tool.exe" if "-windows-" in target else "cine-tool")
    files = [library, cli]
    provenance = {"source_commit": source_commit, "rustc_version": rustc_version}
    if matlab:
        statement = (
            "addpath('Matlab'); build_cine_backend; test_rust_backend; "
            "fprintf('CINE_MATLAB_RELEASE=%s\\n', version('-release'));"
        )
        command = [matlab, *(["-wait"] if os.name == "nt" else []), "-batch", statement]
        result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True)
        print(result.stdout, end="")
        print(result.stderr, end="", file=sys.stderr)
        result.check_returncode()
        provenance["matlab_release"] = next(
            line.removeprefix("CINE_MATLAB_RELEASE=")
            for line in result.stdout.splitlines()
            if line.startswith("CINE_MATLAB_RELEASE=")
        )
        arch, extension = MATLAB_TARGETS[target]
        files.append(ROOT / "Matlab/private" / f"cine_mex.{extension}")
        matlab_library = ROOT / "Matlab/private/lib" / arch / library.name
        if binary.file_digest(matlab_library) != binary.file_digest(library):
            raise RuntimeError("MATLAB's backend differs from the collected Rust release library.")
    current_commit = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
    ).strip()
    if (
        binary.source_fingerprint(ROOT) != before
        or current_commit != source_commit
        or source_status().strip()
    ):
        raise RuntimeError(
            "Native source changed while building; rerun after committing the changes."
        )
    for path in files:
        if not path.is_file():
            raise RuntimeError(f"Build did not produce {path}.")
        if path.stat().st_size >= 100 * 1024 * 1024:
            raise RuntimeError(f"Artifact exceeds GitHub's ordinary Git file-size limit: {path}.")
    metadata = binary.make_manifest(ROOT, target, files, **provenance)
    # Validate in the build directory before replacing any collected artifact.
    (output / binary.MANIFEST_NAME).write_text(
        json.dumps(metadata, indent=2) + "\n", encoding="utf-8"
    )
    binary.validate_library(output, ROOT)
    destination = ROOT / "binaries" / target
    destination.mkdir(parents=True, exist_ok=True)
    for old_gateway in destination.glob("cine_mex.mex*"):
        if old_gateway.name not in {path.name for path in files}:
            old_gateway.unlink()
    for path in files:
        shutil.copy2(path, destination / path.name)
    (destination / binary.MANIFEST_NAME).write_text(
        json.dumps(metadata, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    # IDE/source users can use the same validated backend after a maintainer build.
    package = ROOT / "python/src/cine_reader/libs"
    package.mkdir(parents=True, exist_ok=True)
    shutil.copy2(library, package / library.name)
    (package / binary.MANIFEST_NAME).write_text(
        json.dumps(metadata, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(f"Collected {target} binaries in {destination}")
    return destination


if __name__ == "__main__":
    INCLUDE_MATLAB = True
    collect_binaries(include_matlab=INCLUDE_MATLAB)
