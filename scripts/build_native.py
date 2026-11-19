"""Build the Rust backend for use directly from an IDE or source checkout."""
from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import sys


def build_native(*, release: bool = True, target: str | None = None) -> Path:
    root = Path(__file__).resolve().parents[1]
    target_dir = Path(os.environ.get("CARGO_TARGET_DIR", str(root / "target"))).resolve()
    command = ["cargo", "build", "--locked", "--manifest-path", str(root / "rust/cine-core/Cargo.toml")]
    if release:
        command.append("--release")
    if target:
        command.extend(["--target", target])
    subprocess.run(command, cwd=root, env=dict(os.environ, CARGO_TARGET_DIR=str(target_dir)), check=True)
    platform = target or sys.platform
    name = "cine_core.dll" if "windows" in platform or platform == "win32" else (
        "libcine_core.dylib" if "apple" in platform or platform == "darwin" else "libcine_core.so"
    )
    output = target_dir / target if target else target_dir
    output /= "release" if release else "debug"
    destination = root / "python/src/cine_reader/libs" / name
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(output / name, destination)
    return destination


if __name__ == "__main__":
    RELEASE = True
    TARGET = None  # e.g. "x86_64-apple-darwin"; omit to build for this computer.
    print(build_native(release=RELEASE, target=TARGET))
