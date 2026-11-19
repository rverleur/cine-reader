"""Build the dependency-free Rust shared library into platform-specific wheels."""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

from setuptools import Distribution, setup
from setuptools.command.build_ext import build_ext
from setuptools.command.build_py import build_py
from wheel.bdist_wheel import bdist_wheel

ROOT = Path(__file__).resolve().parent
if sys.platform == "darwin":
    os.environ.setdefault("MACOSX_DEPLOYMENT_TARGET", "11.0")


def build_rust(destination: Path) -> None:
    manifest = ROOT / "rust" / "cine-core" / "Cargo.toml"
    target_dir = Path(os.environ.get("CARGO_TARGET_DIR", str(ROOT / "target"))).resolve()
    target = os.environ.get("CARGO_BUILD_TARGET")
    if target:
        machine = {"arm64": "aarch64", "AMD64": "x86_64"}.get(
            platform.machine(), platform.machine()
        )
        system = (
            "windows"
            if sys.platform == "win32"
            else "apple"
            if sys.platform == "darwin"
            else "linux"
        )
        if not target.startswith(machine + "-") or system not in target:
            raise RuntimeError(
                "Build Python wheels natively on their target OS/CPU; use scripts/build_native.py for cross-built libraries"
            )
    command = ["cargo", "build", "--release", "--locked", "--manifest-path", str(manifest)]
    environment = dict(os.environ, CARGO_TARGET_DIR=str(target_dir))
    subprocess.run(command, cwd=ROOT, env=environment, check=True)
    target = os.environ.get("CARGO_BUILD_TARGET")
    output = target_dir / target / "release" if target else target_dir / "release"
    library = (
        "cine_core.dll"
        if sys.platform == "win32"
        else ("libcine_core.dylib" if sys.platform == "darwin" else "libcine_core.so")
    )
    destination.mkdir(parents=True, exist_ok=True)
    for pattern in ("*.dll", "*.dylib", "*.so"):
        for stale in destination.glob(pattern):
            stale.unlink()
    shutil.copy2(output / library, destination / library)


class RustBuildPy(build_py):
    def run(self):
        super().run()
        build_rust(Path(self.build_lib) / "cine_reader" / "libs")


class RustBuildExt(build_ext):
    def run(self):
        destination = (
            ROOT / "python" / "src" / "cine_reader" / "libs"
            if self.inplace
            else (Path(self.build_lib) / "cine_reader" / "libs")
        )
        build_rust(destination)


class BinaryDistribution(Distribution):
    def has_ext_modules(self):
        return True


class RustWheel(bdist_wheel):
    def get_tag(self):
        _, _, platform_tag = super().get_tag()
        if sys.platform == "darwin":
            # No CPython extension is linked: its own deployment floor does not
            # constrain this independent Rust/ctypes library.
            version = os.environ["MACOSX_DEPLOYMENT_TARGET"].split(".")
            major, minor = int(version[0]), int(version[1]) if len(version) > 1 else 0
            platform_tag = f"macosx_{major}_{minor}_{platform.machine()}"
        return "py3", "none", platform_tag


setup(
    distclass=BinaryDistribution,
    cmdclass={"build_py": RustBuildPy, "build_ext": RustBuildExt, "bdist_wheel": RustWheel},
)
