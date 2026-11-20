"""Build the Rust backend for use directly from an IDE or source checkout."""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path


def build_native(*, release: bool = True, target: str | None = None) -> Path:
    root = Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location(
        "cine_binary_native_build", root / "python/src/cine_reader/_binary.py"
    )
    binary = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(binary)
    native_target = binary.host_target()
    if target is not None and target != native_target:
        raise RuntimeError(
            "Build this helper natively; use Cargo directly for unsupported cross builds."
        )
    binary.check_build_environment(root)
    if sys.platform == "darwin":
        os.environ.setdefault("MACOSX_DEPLOYMENT_TARGET", "11.0")
    target_dir = Path(os.environ.get("CARGO_TARGET_DIR", str(root / "target")))
    if not target_dir.is_absolute():
        target_dir = root / target_dir
    target_dir = target_dir.resolve()
    command = [
        "cargo",
        "build",
        "--locked",
        "--manifest-path",
        str(root / "rust/cine-core/Cargo.toml"),
    ]
    if release:
        command.append("--release")
    if target:
        command.extend(["--target", target])
    subprocess.run(
        command, cwd=root, env=dict(os.environ, CARGO_TARGET_DIR=str(target_dir)), check=True
    )
    name = binary.library_name(native_target)
    output = target_dir / target if target else target_dir
    output /= "release" if release else "debug"
    metadata = binary.make_manifest(
        root,
        native_target,
        [output / name],
        rustc_version=subprocess.check_output(["rustc", "-vV"], text=True).strip(),
        build_profile="release" if release else "debug",
    )
    (output / binary.MANIFEST_NAME).write_text(
        json.dumps(metadata, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    binary.validate_library(output, root)
    destination = root / "python/src/cine_reader/libs" / name
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(output / name, destination)
    shutil.copy2(output / binary.MANIFEST_NAME, destination.parent / binary.MANIFEST_NAME)
    return destination


if __name__ == "__main__":
    RELEASE = True
    TARGET = None  # Omit or use this computer's native Rust target only.
    print(build_native(release=RELEASE, target=TARGET))
