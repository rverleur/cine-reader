"""Reject incomplete, stale, relabeled or corrupted distribution sets before publishing."""

from __future__ import annotations

import base64
import csv
import hashlib
import importlib.util
import io
import json
import os
import shutil
import subprocess
import tarfile
import zipfile
from pathlib import Path

import pytest

PROJECT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("release_checks", PROJECT / "scripts/release.py")
release = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release)


@pytest.fixture
def checkout(tmp_path):
    root = tmp_path / "clean checkout"
    release.source_snapshot(PROJECT, root)
    # These unit fixtures are deliberately independent of production artifact
    # currency. Rust source commits must pass before the collector can rebuild
    # each platform. Only the release gate validates the real collected files.
    binary = release.binary_module(root)
    fingerprint = binary.source_fingerprint(root)
    for path in (root / "binaries").glob("*/build-info.json"):
        metadata = json.loads(path.read_text())
        metadata["source_fingerprint"] = fingerprint
        metadata["abi_version"] = binary.ABI_VERSION
        path.write_text(json.dumps(metadata), encoding="utf-8")
    return root


def wheel_files(root, target):
    version = release.package_version(root)
    info = f"cine_handler-{version}.dist-info"
    collected = root / "binaries" / target
    metadata = json.loads((collected / "build-info.json").read_text())
    library = release.binary_module(root).library_name(target)
    metadata["artifacts"] = {library: metadata["artifacts"][library]}
    return {
        "cine_reader/__init__.py": b"# Distribution verification fixture.\n",
        f"cine_reader/libs/{library}": (collected / library).read_bytes(),
        "cine_reader/libs/build-info.json": json.dumps(metadata).encode(),
        f"{info}/METADATA": f"Metadata-Version: 2.4\nName: cine-handler\nVersion: {version}\n".encode(),
        f"{info}/WHEEL": (
            f"Wheel-Version: 1.0\nRoot-Is-Purelib: false\nTag: py3-none-{release.TARGET_TAGS[target]}\n"
        ).encode(),
        f"{info}/licenses/LICENSE": (root / "LICENSE").read_bytes(),
    }


def write_wheel(root, destination, target, files, *, broken_record=False):
    version = release.package_version(root)
    record_name = f"cine_handler-{version}.dist-info/RECORD"
    record = io.StringIO()
    writer = csv.writer(record)
    for name, data in files.items():
        digest = base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b"=").decode()
        writer.writerow((name, f"sha256={digest}", len(data)))
    writer.writerow((record_name, "", ""))
    files = dict(files, **{record_name: record.getvalue().encode()})
    if broken_record:
        files["cine_reader/__init__.py"] += b"# Changed after RECORD creation.\n"
    destination.mkdir(exist_ok=True)
    path = destination / f"cine_handler-{version}-py3-none-{release.TARGET_TAGS[target]}.whl"
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, data in files.items():
            archive.writestr(name, data)
    return path


def write_sdist(root, destination, *, remove=None, extra=None):
    version = release.package_version(root)
    prefix = f"cine_handler-{version}"
    files = {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file() and "__pycache__" not in path.parts
    }
    files["PKG-INFO"] = f"Metadata-Version: 2.4\nName: cine-handler\nVersion: {version}\n".encode()
    if remove:
        files.pop(remove)
    if extra:
        files.update(extra)
    destination.mkdir(exist_ok=True)
    path = destination / f"{prefix}.tar.gz"
    with tarfile.open(path, "w:gz") as archive:
        for name, data in files.items():
            info = tarfile.TarInfo(f"{prefix}/{name}")
            info.size = len(data)
            archive.addfile(info, io.BytesIO(data))
    return path


def test_release_version_and_tag_must_agree():
    version = release.package_version(PROJECT)
    release.validate_tag(PROJECT, None)
    release.validate_tag(PROJECT, f"v{version}")
    with pytest.raises(ValueError, match="does not match"):
        release.validate_tag(PROJECT, version)
    with pytest.raises(ValueError, match="does not match"):
        release.validate_tag(PROJECT, "v999.0.0")


def test_windows_git_checkout_preserves_license_bytes(tmp_path, monkeypatch):
    # Assembly verifies a Windows-built wheel against a Linux checkout. Git must
    # not introduce CRLF into the license on the Windows packaging runner.
    for name in tuple(os.environ):
        if name.startswith("GIT_"):
            monkeypatch.delenv(name)
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)
    root = tmp_path / "windows checkout"
    root.mkdir()
    expected = (PROJECT / "LICENSE").read_bytes().replace(b"\r\n", b"\n")
    (root / "LICENSE").write_bytes(expected)
    shutil.copyfile(PROJECT / ".gitattributes", root / ".gitattributes")

    def git(*arguments):
        subprocess.run(["git", "-C", str(root), *arguments], capture_output=True, check=True)

    git("init", "--quiet")
    git("config", "core.autocrlf", "true")
    git("add", ".gitattributes", "LICENSE")
    (root / "LICENSE").unlink()
    git("checkout-index", "--force", "--all")
    assert (root / "LICENSE").read_bytes() == expected


def test_complete_collection_passes(checkout):
    assert set(release.validate_collection(checkout)) == set(release.TARGET_TAGS)


@pytest.mark.parametrize("damage", ["source", "library", "missing-matlab", "missing-target"])
def test_collection_rejects_stale_or_incomplete_artifacts(checkout, damage):
    target = checkout / "binaries/x86_64-pc-windows-msvc"
    if damage == "source":
        with (checkout / "rust/cine-core/src/lib.rs").open("ab") as stream:
            stream.write(b"\n// Different Rust input.\n")
    elif damage == "library":
        path = target / "cine_core.dll"
        path.write_bytes(path.read_bytes() + b"corruption")
    elif damage == "missing-matlab":
        (target / "cine_mex.mexw64").unlink()
    else:
        shutil.rmtree(target)
    with pytest.raises((ValueError, OSError)):
        release.validate_collection(checkout)


@pytest.mark.parametrize("target", list(release.TARGET_TAGS))
def test_each_wheel_contains_only_its_matching_verified_backend(checkout, tmp_path, target):
    wheel = write_wheel(checkout, tmp_path, target, wheel_files(checkout, target))
    assert release.verify_wheel(checkout, wheel) == target


@pytest.mark.parametrize(
    "damage", ["version", "internal-tag", "extra-library", "backend", "record", "license"]
)
def test_wheel_rejects_distribution_corruption(checkout, tmp_path, damage):
    target = "x86_64-pc-windows-msvc"
    files = wheel_files(checkout, target)
    info = f"cine_handler-{release.package_version(checkout)}.dist-info"
    if damage == "version":
        files[f"{info}/METADATA"] = b"Name: cine-handler\nVersion: 999.0.0\n"
    elif damage == "internal-tag":
        files[f"{info}/WHEEL"] = b"Root-Is-Purelib: false\nTag: py3-none-any\n"
    elif damage == "extra-library":
        files["cine_reader/libs/other.dll"] = b"not this target"
    elif damage == "backend":
        files["cine_reader/libs/cine_core.dll"] += b"corrupted native binary"
    elif damage == "license":
        files[f"{info}/licenses/LICENSE"] = b"Not the project license"
    wheel = write_wheel(checkout, tmp_path, target, files, broken_record=damage == "record")
    with pytest.raises(ValueError):
        release.verify_wheel(checkout, wheel)


def test_generic_linux_tag_cannot_be_published(checkout, tmp_path):
    target = "x86_64-unknown-linux-gnu"
    wheel = write_wheel(checkout, tmp_path, target, wheel_files(checkout, target))
    unaudited = wheel.with_name(wheel.name.replace("manylinux_2_28_x86_64", "linux_x86_64"))
    wheel.rename(unaudited)
    with pytest.raises(ValueError, match="unaudited"):
        release.verify_wheel(checkout, unaudited)


def test_complete_distribution_set_preserves_all_targets(checkout, tmp_path):
    output = tmp_path / "distributions"
    for target in release.TARGET_TAGS:
        write_wheel(checkout, output, target, wheel_files(checkout, target))
    write_sdist(checkout, output)
    release.verify_distribution_set(checkout, output)
    extra = output / "unreviewed-extra.zip"
    extra.write_bytes(b"not part of the release")
    with pytest.raises(ValueError, match="exactly three"):
        release.verify_distribution_set(checkout, output)
    extra.unlink()
    next(output.glob("*.whl")).unlink()
    with pytest.raises(ValueError, match="exactly three"):
        release.verify_distribution_set(checkout, output)


@pytest.mark.parametrize(
    "damage", ["missing-matlab", "missing-attributes", "recording", "local-library", "rust-source"]
)
def test_sdist_rejects_missing_interfaces_and_stale_or_local_outputs(checkout, tmp_path, damage):
    remove = {"missing-matlab": "Matlab/Cine.m", "missing-attributes": ".gitattributes"}.get(damage)
    extras = {
        "recording": {"sample_data/local.cine": b"private camera recording"},
        "local-library": {"Matlab/private/lib/local.so": b"uncollected binary"},
        "rust-source": {"rust/cine-core/src/lib.rs": b"// Not the collected source\n"},
    }.get(damage)
    archive = write_sdist(checkout, tmp_path / "distributions", remove=remove, extra=extras)
    with pytest.raises(ValueError):
        release.verify_sdist(checkout, archive)


def test_snapshot_excludes_generated_outputs_and_private_camera_files(checkout, tmp_path):
    for name in (
        "python/examples/output/generated.cine",
        "Matlab/examples/output/generated.png",
        "python/src/cine_reader/libs/local.dylib",
        "Matlab/private/cine_mex.mexmaca64",
        "Matlab/private/lib/maca64/local.dylib",
        "sample_data/private.cine",
    ):
        path = checkout / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"local output")
    snapshot = tmp_path / "snapshot"
    release.source_snapshot(checkout, snapshot)
    assert not (snapshot / "python/examples/output").exists()
    assert not (snapshot / "Matlab/examples/output").exists()
    assert not (snapshot / "python/src/cine_reader/libs").exists()
    assert not (snapshot / "Matlab/private/lib").exists()
    assert not (snapshot / "Matlab/private/cine_mex.mexmaca64").exists()
    assert {p.name for p in (snapshot / "sample_data").iterdir()} == {"README.md"}
