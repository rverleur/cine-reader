"""Package a verified prebuilt backend; compilation is a maintainer opt-in."""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from setuptools import Distribution, setup
from setuptools.command.bdist_wheel import bdist_wheel
from setuptools.command.build_ext import build_ext
from setuptools.command.build_py import build_py

ROOT = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location(
    "cine_binary_build", ROOT / "python/src/cine_reader/_binary.py"
)
binary = importlib.util.module_from_spec(spec)
spec.loader.exec_module(binary)
_selection = None


def selected_binary():
    global _selection
    if _selection is not None:
        return _selection
    if os.environ.get("CINE_BUILD_RUST") != "1":
        _selection = binary.select_prebuilt(ROOT)
        return _selection
    binary.check_build_environment(ROOT)
    target = binary.host_target()
    if sys.platform == "darwin":
        os.environ.setdefault("MACOSX_DEPLOYMENT_TARGET", "11.0")
    target_dir = Path(os.environ.get("CARGO_TARGET_DIR", str(ROOT / "target")))
    if not target_dir.is_absolute():
        target_dir = ROOT / target_dir
    target_dir = target_dir.resolve()
    subprocess.run(
        ["cargo", "build", "--release", "--workspace", "--locked", "--target", target],
        cwd=ROOT,
        env=dict(os.environ, CARGO_TARGET_DIR=str(target_dir)),
        check=True,
    )
    output = target_dir / target / "release"
    library = output / binary.library_name(target)
    metadata = binary.make_manifest(
        ROOT,
        target,
        [library],
        rustc_version=subprocess.check_output(["rustc", "-vV"], text=True).strip(),
        build_method="explicit CINE_BUILD_RUST=1",
    )
    (output / binary.MANIFEST_NAME).write_text(
        json.dumps(metadata, indent=2) + "\n", encoding="utf-8"
    )
    _selection = binary.validate_library(output, ROOT)
    return _selection


def install_binary(destination: Path) -> None:
    library, metadata = selected_binary()
    destination.mkdir(parents=True, exist_ok=True)
    for pattern in ("*.dll", "*.dylib", "*.so"):
        for stale in destination.glob(pattern):
            stale.unlink()
    shutil.copy2(library, destination / library.name)
    # Only the shared backend belongs in a Python wheel, even if the repository
    # manifest also describes the standalone program or MATLAB gateway.
    metadata = dict(metadata, artifacts={library.name: metadata["artifacts"][library.name]})
    (destination / binary.MANIFEST_NAME).write_text(
        json.dumps(metadata, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


class RustBuildPy(build_py):
    def run(self):
        super().run()
        install_binary(Path(self.build_lib) / "cine_reader" / "libs")


class RustBuildExt(build_ext):
    def run(self):
        destination = (
            ROOT / "python" / "src" / "cine_reader" / "libs"
            if self.inplace
            else (Path(self.build_lib) / "cine_reader" / "libs")
        )
        install_binary(destination)


class BinaryDistribution(Distribution):
    def has_ext_modules(self):
        return True


class RustWheel(bdist_wheel):
    def get_tag(self):
        _, metadata = selected_binary()
        target = metadata["target"]
        arm = target.startswith("aarch64-")
        if target.endswith("-apple-darwin"):
            major, minor, _ = binary.version_tuple(metadata["macos_deployment_target"])
            platform_tag = f"macosx_{major}_{minor}_{'arm64' if arm else 'x86_64'}"
        elif "-windows-" in target:
            platform_tag = "win_arm64" if arm else "win_amd64"
        else:
            # A native Linux build has not been audited for manylinux/musllinux.
            platform_tag = "linux_aarch64" if arm else "linux_x86_64"
        if self.plat_name_supplied and self.plat_name != platform_tag:
            raise RuntimeError("A platform override cannot relabel this native backend.")
        return "py3", "none", platform_tag


setup(
    distclass=BinaryDistribution,
    cmdclass={"build_py": RustBuildPy, "build_ext": RustBuildExt, "bdist_wheel": RustWheel},
)
