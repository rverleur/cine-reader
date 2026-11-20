"""Package and verify collected backends without compiling Rust. Configure __main__ for an IDE."""

from __future__ import annotations

import base64
import csv
import hashlib
import importlib.util
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import zipfile
from email.parser import BytesParser
from pathlib import Path, PurePosixPath

from packaging.utils import canonicalize_name, parse_sdist_filename, parse_wheel_filename
from packaging.version import Version

ROOT = Path(__file__).resolve().parents[1]
TARGET_TAGS = {
    "aarch64-apple-darwin": "macosx_11_0_arm64",
    "x86_64-pc-windows-msvc": "win_amd64",
    "x86_64-unknown-linux-gnu": "manylinux_2_28_x86_64",
}
SOURCE_ENTRIES = (
    "pyproject.toml",
    "setup.py",
    "MANIFEST.in",
    "README.md",
    "PYPI.md",
    "LICENSE",
    "CHANGELOG.md",
    "Cargo.toml",
    "Cargo.lock",
    "pytest.ini",
    "miss_hit.cfg",
    ".cargo",
    ".githooks",
    ".github",
    "rust",
    "python",
    "Matlab",
    "scripts",
    "docs",
    "binaries",
    "sample_data/README.md",
)


def binary_module(root: Path):
    spec = importlib.util.spec_from_file_location(
        "release_binary", root / "python/src/cine_reader/_binary.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def package_version(root: Path) -> str:
    """Read the single static project version, including on supported Python 3.9."""
    text = (root / "pyproject.toml").read_text(encoding="utf-8")
    section = re.search(r"(?ms)^\[project\]\s*\n(.*?)(?=^\[|\Z)", text)
    versions = re.findall(
        r"(?m)^version\s*=\s*['\"]([^'\"]+)['\"]\s*(?:#.*)?$",
        section[1] if section else "",
    )
    if len(versions) != 1 or str(Version(versions[0])) != versions[0]:
        raise ValueError("Expected one normalized static [project] version in pyproject.toml.")
    return versions[0]


def validate_tag(root: Path, tag: str | None) -> None:
    if tag and tag != f"v{package_version(root)}":
        raise ValueError(
            f"Release tag {tag!r} does not match required tag 'v{package_version(root)}'."
        )


def validate_collection(root: Path) -> dict[str, dict]:
    """Verify every distributed target, independently of the build machine's OS."""
    binary = binary_module(root)
    fingerprint = binary.source_fingerprint(root)
    manifests = {}
    directories = {path.name for path in (root / "binaries").iterdir() if path.is_dir()}
    if directories != set(TARGET_TAGS):
        raise ValueError("Collected target directories do not match the release platform matrix.")
    for target in TARGET_TAGS:
        directory = root / "binaries" / target
        metadata = json.loads((directory / binary.MANIFEST_NAME).read_text(encoding="utf-8"))
        if (
            type(metadata.get("schema_version")) is not int
            or metadata["schema_version"] != 1
            or type(metadata.get("abi_version")) is not int
            or metadata["abi_version"] != binary.ABI_VERSION
            or metadata.get("target") != target
            or metadata.get("source_fingerprint") != fingerprint
        ):
            raise ValueError(f"Stale or incompatible collected manifest: {target}.")
        library = binary.library_name(target)
        cli = "cine-tool.exe" if "windows" in target else "cine-tool"
        mex = {
            "aarch64-apple-darwin": "cine_mex.mexmaca64",
            "x86_64-pc-windows-msvc": "cine_mex.mexw64",
            "x86_64-unknown-linux-gnu": "cine_mex.mexa64",
        }[target]
        artifacts = metadata.get("artifacts")
        if not isinstance(artifacts, dict) or set(artifacts) != {library, cli, mex}:
            raise ValueError(f"Incomplete or unexpected collected artifacts: {target}.")
        if {path.name for path in directory.iterdir()} != {*artifacts, binary.MANIFEST_NAME}:
            raise ValueError(f"Unrecorded files in collected artifacts: {target}.")
        for name, record in artifacts.items():
            path = directory / name
            actual = {"size": path.stat().st_size, "sha256": binary.file_digest(path)}
            if record != actual:
                raise ValueError(f"Collected artifact checksum/size mismatch: {target}/{name}.")
            binary._native_header(path, target)
        if "apple" in target:
            minimum = binary._native_header(directory / library, target)
            declared = binary.version_tuple(metadata.get("macos_deployment_target"))
            if declared != (11, 0, 0) or minimum > declared:
                raise ValueError("The macOS deployment floor does not match the release wheel tag.")
        if "linux" in target and metadata.get("libc") != {
            "name": "glibc",
            "minimum_version": "2.28",
        }:
            raise ValueError("The Linux libc floor does not match the audited release policy.")
        manifests[target] = metadata
    return manifests


def source_snapshot(root: Path, destination: Path) -> None:
    """Copy current sources and collected artifacts, excluding local build products and data."""

    def ignore(folder, names):
        path = Path(folder)
        excluded = {
            name
            for name in names
            if name in {"__pycache__", ".pytest_cache", ".ruff_cache", ".DS_Store"}
            or name.endswith((".pyc", ".pyo", ".egg-info"))
            or Path(name).suffix.lower()
            in {".cine", ".tif", ".tiff", ".png", ".jpg", ".jpeg", ".mp4", ".avi", ".mkv", ".npz"}
        }
        if path in {root / "python/examples", root / "Matlab/examples"}:
            excluded.add("output")
        if path == root / "python/src/cine_reader":
            excluded.add("libs")
        if path == root / "Matlab/private":
            excluded.add("lib")
            excluded.update(name for name in names if name.startswith("cine_mex.mex"))
        return excluded

    destination.mkdir(parents=True)
    for name in SOURCE_ENTRIES:
        path = root / name
        if path.is_dir():
            shutil.copytree(path, destination / name, ignore=ignore)
        elif path.is_file():
            (destination / name).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, destination / name)


def _safe_names(names: list[str]) -> None:
    if len(names) != len(set(names)):
        raise ValueError("Distribution contains duplicate archive members.")
    for name in names:
        path = PurePosixPath(name)
        if path.is_absolute() or ".." in path.parts or "\\" in name:
            raise ValueError(f"Unsafe distribution member: {name}.")


def verify_wheel(root: Path, wheel: Path, manifests: dict[str, dict] | None = None) -> str:
    manifests = validate_collection(root) if manifests is None else manifests
    name, version, build, tags = parse_wheel_filename(wheel.name)
    if name != "cine-handler" or str(version) != package_version(root) or build:
        raise ValueError(f"Unexpected wheel name or version: {wheel.name}.")
    target = next(
        (
            target
            for target, tag in TARGET_TAGS.items()
            if {str(t) for t in tags} == {f"py3-none-{tag}"}
        ),
        None,
    )
    if target is None:
        raise ValueError(f"Unexpected or unaudited wheel tag: {wheel.name}.")
    binary = binary_module(root)
    info = f"cine_handler-{version}.dist-info"
    with zipfile.ZipFile(wheel) as archive:
        names = archive.namelist()
        _safe_names(names)
        files = {name for name in names if not name.endswith("/")}
        wheel_metadata = BytesParser().parsebytes(archive.read(f"{info}/WHEEL"))
        if wheel_metadata.get_all("Tag") != [f"py3-none-{TARGET_TAGS[target]}"]:
            raise ValueError("Wheel filename and internal platform tags disagree.")
        if wheel_metadata.get("Root-Is-Purelib", "").lower() != "false":
            raise ValueError("Native backend wheel must not claim to be pure Python.")
        metadata = BytesParser().parsebytes(archive.read(f"{info}/METADATA"))
        if canonicalize_name(metadata.get("Name", "")) != name or metadata.get("Version") != str(
            version
        ):
            raise ValueError("Wheel METADATA name/version differs from its filename.")
        if archive.read(f"{info}/licenses/LICENSE") != (root / "LICENSE").read_bytes():
            raise ValueError("Wheel license differs from the project license.")
        library_name = binary.library_name(target)
        library_path = f"cine_reader/libs/{library_name}"
        manifest_path = f"cine_reader/libs/{binary.MANIFEST_NAME}"
        if {name for name in files if name.startswith("cine_reader/libs/")} != {
            library_path,
            manifest_path,
        }:
            raise ValueError("A wheel must contain exactly its own library and build manifest.")
        for member in files:
            if member != library_path and member.endswith(
                (".so", ".dll", ".dylib", ".exe", ".mexa64", ".mexw64", ".mexmaca64")
            ):
                raise ValueError(f"Unexpected additional native artifact in wheel: {member}.")
        library_bytes = archive.read(library_path)
        expected = manifests[target]
        record = {"size": len(library_bytes), "sha256": hashlib.sha256(library_bytes).hexdigest()}
        if record != expected["artifacts"][library_name]:
            raise ValueError("Packaged library differs from the verified collected artifact.")
        packaged = json.loads(archive.read(manifest_path))
        if packaged != dict(expected, artifacts={library_name: record}):
            raise ValueError("Packaged manifest does not match its verified collected artifact.")
        rows = list(csv.reader(io.StringIO(archive.read(f"{info}/RECORD").decode())))
        if any(len(row) != 3 for row in rows) or len(rows) != len({row[0] for row in rows}):
            raise ValueError("Malformed or duplicate wheel RECORD entries.")
        if {row[0] for row in rows} != files:
            raise ValueError("Wheel RECORD does not cover every packaged file.")
        for member, digest, size in rows:
            if member == f"{info}/RECORD":
                if digest or size:
                    raise ValueError("Wheel RECORD must not hash itself.")
                continue
            data = archive.read(member)
            expected_digest = (
                base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b"=").decode()
            )
            if digest != f"sha256={expected_digest}" or size != str(len(data)):
                raise ValueError(f"Wheel RECORD checksum/size mismatch: {member}.")
    print(f"Verified {wheel.name}")
    return target


def verify_sdist(root: Path, archive_path: Path, manifests: dict[str, dict] | None = None) -> None:
    manifests = validate_collection(root) if manifests is None else manifests
    name, version = parse_sdist_filename(archive_path.name)
    if name != "cine-handler" or str(version) != package_version(root):
        raise ValueError(f"Unexpected source archive name/version: {archive_path.name}.")
    prefix = f"cine_handler-{version}/"
    required = {
        "LICENSE",
        "README.md",
        "PYPI.md",
        "CHANGELOG.md",
        "MANIFEST.in",
        "setup.py",
        "pyproject.toml",
        "Cargo.toml",
        "Cargo.lock",
        ".cargo/config.toml",
        "python/src/cine_reader/_binary.py",
        "python/src/cine_reader/_native.py",
        "python/README.md",
        "python/API.md",
        "Matlab/Cine.m",
        "Matlab/CineWriter.m",
        "Matlab/README.md",
        "Matlab/API.md",
        "docs/BUILDING.md",
        "docs/DEVELOPMENT.md",
        "docs/RELEASING.md",
        "scripts/install_hooks.py",
        ".githooks/pre-commit",
    }
    with tarfile.open(archive_path, "r:gz") as archive:
        members = archive.getmembers()
        _safe_names([member.name for member in members])
        if any(not (member.isfile() or member.isdir()) for member in members):
            raise ValueError("Source archive contains links or special files.")
        if any(not member.name.startswith(prefix) for member in members if member.isfile()):
            raise ValueError("Source archive contains unexpected top-level paths.")
        files = {member.name[len(prefix) :]: member for member in members if member.isfile()}
        if not required <= files.keys():
            raise ValueError(
                f"Source archive is missing required files: {sorted(required - files.keys())}."
            )
        forbidden = {"c_src", "release", "build", "dist", "target", ".git", ".venv", "__pycache__"}
        if any(forbidden.intersection(PurePosixPath(name).parts) for name in files):
            raise ValueError("Source archive contains obsolete or local build/data files.")
        if any(
            name.startswith("sample_data/") and name != "sample_data/README.md" for name in files
        ):
            raise ValueError("Source archive contains local sample recordings.")
        if any(
            name.lower().endswith(".cine")
            or name.startswith(("python/src/cine_reader/libs/", "Matlab/private/lib/"))
            or (name.startswith("Matlab/private/") and ".mex" in name)
            for name in files
        ):
            raise ValueError(
                "Source archive contains recordings or uncollected local native outputs."
            )
        for folder in ("python/examples", "Matlab/examples"):
            if not any(name.startswith(folder + "/") for name in files):
                raise ValueError(f"Source archive is missing {folder}.")

        def read(relative):
            return archive.extractfile(files[relative]).read()

        metadata = BytesParser().parsebytes(read("PKG-INFO"))
        if canonicalize_name(metadata.get("Name", "")) != name or metadata.get("Version") != str(
            version
        ):
            raise ValueError("Source archive metadata differs from its filename.")
        for target, expected in manifests.items():
            folder = f"binaries/{target}"
            if json.loads(read(f"{folder}/build-info.json")) != expected:
                raise ValueError(f"Source archive manifest differs for {target}.")
            for filename, record in expected["artifacts"].items():
                data = read(f"{folder}/{filename}")
                if {"size": len(data), "sha256": hashlib.sha256(data).hexdigest()} != record:
                    raise ValueError(f"Source archive artifact differs: {target}/{filename}.")
        with tempfile.TemporaryDirectory(prefix="cine-sdist-verify-") as temporary:
            extracted = Path(temporary)
            for relative in files:
                if relative.startswith(("rust/cine-core/", ".cargo/")) or relative in {
                    "Cargo.toml",
                    "Cargo.lock",
                }:
                    destination = extracted / relative
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    destination.write_bytes(read(relative))
            binary = binary_module(root)
            if binary.source_fingerprint(extracted) != binary.source_fingerprint(root):
                raise ValueError(
                    "Source archive Rust fingerprint differs from the collected binaries."
                )
    print(f"Verified {archive_path.name}")


def verify_distribution_set(root: Path, directory: Path) -> None:
    manifests = validate_collection(root)
    wheels = sorted(directory.glob("*.whl"))
    sdists = sorted(directory.glob("*.tar.gz"))
    if (
        len(wheels) != len(TARGET_TAGS)
        or len(sdists) != 1
        or set(directory.iterdir()) != set(wheels + sdists)
    ):
        raise ValueError(
            "A release must contain exactly three platform wheels and one source archive."
        )
    targets = [verify_wheel(root, wheel, manifests) for wheel in wheels]
    if set(targets) != set(TARGET_TAGS) or len(set(targets)) != len(targets):
        raise ValueError("Release wheel set has duplicate or missing platforms.")
    verify_sdist(root, sdists[0], manifests)


def clean_environment() -> dict[str, str]:
    environment = {
        name: value
        for name, value in os.environ.items()
        if not name.startswith(("CINE_", "CARGO_", "RUST", "PYTHON", "PIP_"))
        and name
        not in {"LD_LIBRARY_PATH", "LD_PRELOAD", "DYLD_LIBRARY_PATH", "DYLD_INSERT_LIBRARIES"}
    }
    environment.update(
        PYTHONNOUSERSITE="1", PYTEST_DISABLE_PLUGIN_AUTOLOAD="1", PIP_CONFIG_FILE=os.devnull
    )
    return environment


def build_distributions(root: Path, output: Path, *, include_sdist: bool = True) -> None:
    manifests = validate_collection(root)
    binary = binary_module(root)
    target = binary.host_target()
    if target not in TARGET_TAGS:
        raise ValueError(f"This release has no collected backend for {target}.")
    if output.exists() and any(output.iterdir()):
        raise ValueError(f"Choose an empty distribution output directory: {output}.")
    output.mkdir(parents=True, exist_ok=True)
    environment = clean_environment()
    with tempfile.TemporaryDirectory(prefix="cine-release-build-") as temporary:
        work = Path(temporary)
        snapshot = work / "source"
        source_snapshot(root, snapshot)
        raw = work / "raw"
        subprocess.run(
            [sys.executable, "-m", "build", "--wheel", "--outdir", str(raw)],
            cwd=snapshot,
            env=environment,
            check=True,
        )
        (wheel,) = raw.glob("*.whl")
        if "linux" in target:
            repaired = work / "portable"
            subprocess.run(
                [sys.executable, "-m", "auditwheel", "show", str(wheel)],
                env=environment,
                check=True,
            )
            subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "auditwheel",
                    "repair",
                    "--plat",
                    TARGET_TAGS[target],
                    "--only-plat",
                    "--wheel-dir",
                    str(repaired),
                    str(wheel),
                ],
                env=environment,
                check=True,
            )
            (wheel,) = repaired.glob("*.whl")
            subprocess.run(
                [sys.executable, "-m", "auditwheel", "show", str(wheel)],
                env=environment,
                check=True,
            )
        verify_wheel(root, wheel, manifests)
        artifacts = [wheel]
        if include_sdist:
            subprocess.run(
                [sys.executable, "-m", "build", "--sdist", "--outdir", str(raw)],
                cwd=snapshot,
                env=environment,
                check=True,
            )
            (sdist,) = raw.glob("*.tar.gz")
            verify_sdist(root, sdist, manifests)
            artifacts.append(sdist)
        subprocess.run(
            [sys.executable, "-m", "twine", "check", *map(str, artifacts)],
            env=environment,
            check=True,
        )
        for artifact in artifacts:
            shutil.copy2(artifact, output / artifact.name)
    print(f"Built verified distributions from collected binaries in {output}")


if __name__ == "__main__":
    # Edit these values for an IDE run. CI supplies the same settings through the environment.
    MODE = os.environ.get("CINE_RELEASE_MODE", "build")
    OUTPUT = Path(os.environ.get("CINE_RELEASE_OUTPUT", str(ROOT / "dist/release"))).resolve()
    INCLUDE_SDIST = os.environ.get("CINE_RELEASE_SDIST", "1") == "1"
    RELEASE_TAG = os.environ.get("CINE_RELEASE_TAG")
    validate_tag(ROOT, RELEASE_TAG)
    if MODE == "build":
        build_distributions(ROOT, OUTPUT, include_sdist=INCLUDE_SDIST)
    elif MODE == "validate":
        verify_distribution_set(ROOT, OUTPUT)
    else:
        raise ValueError("CINE_RELEASE_MODE must be 'build' or 'validate'.")
