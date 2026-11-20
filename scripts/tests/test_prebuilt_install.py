"""Keep ordinary installations compiler-free and reject incompatible native artifacts."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import runpy
import shutil
import struct
import subprocess
from pathlib import Path

import pytest
import setuptools

PROJECT = Path(__file__).resolve().parents[2]


@pytest.fixture
def source_root(tmp_path):
    root = tmp_path / "checkout with spaces"
    sources = {
        "Cargo.toml": '[workspace]\nmembers = ["rust/cine-core"]\n',
        "Cargo.lock": "version = 4\n",
        "rust/cine-core/Cargo.toml": '[package]\nname = "cine-core"\nversion = "0.2.0"\n',
        "rust/cine-core/src/lib.rs": "pub fn example() {}\n",
        "rust/cine-core/include/cine_core.h": "#define CINE_ABI_VERSION 1\n",
        ".cargo/config.toml": "# Portable compiler defaults.\n",
    }
    for name, text in sources.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(text.encode())
    return root


@pytest.fixture
def binary():
    spec = importlib.util.spec_from_file_location(
        "prebuilt_validation_test", PROJECT / "python/src/cine_reader/_binary.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def set_host(monkeypatch, binary, target, *, version="14.0", libc=("glibc", "2.35")):
    machine = "arm64" if target.startswith("aarch64-") else "AMD64"
    system = "Darwin" if "apple" in target else "Windows" if "windows" in target else "Linux"
    monkeypatch.setattr(binary.platform, "system", lambda: system)
    monkeypatch.setattr(binary.platform, "machine", lambda: machine)
    monkeypatch.setattr(binary.platform, "mac_ver", lambda: (version, ("", "", ""), machine))
    monkeypatch.setattr(binary, "linux_libc", lambda: libc)


def native_header(target, *, minimum=(11, 0, 0)):
    arm = target.startswith("aarch64-")
    if "windows" in target:
        header = bytearray(64 + 24 + 240)
        header[:2] = b"MZ"
        struct.pack_into("<I", header, 60, 64)
        header[64:68] = b"PE\0\0"
        struct.pack_into("<H", header, 68, 0xAA64 if arm else 0x8664)
        struct.pack_into("<HHH", header, 84, 240, 0x2000, 0x20B)
        return bytes(header)
    if "apple" in target:
        cpu = 0x0100000C if arm else 0x01000007
        packed_version = minimum[0] << 16 | minimum[1] << 8 | minimum[2]
        return struct.pack("<8I", 0xFEEDFACF, cpu, 0, 6, 1, 24, 0, 0) + struct.pack(
            "<6I", 0x32, 24, 1, packed_version, packed_version, 0
        )
    header = bytearray(64)
    header[:7] = b"\x7fELF\x02\x01\x01"
    struct.pack_into("<HHI", header, 16, 3, 183 if arm else 62, 1)
    return bytes(header)


def prebuilt(binary, root, target, *, payload=None, **metadata_fields):
    directory = root / "binaries" / target
    directory.mkdir(parents=True)
    library = directory / binary.library_name(target)
    payload = native_header(target) if payload is None else payload
    library.write_bytes(payload)
    metadata = {
        "schema_version": 1,
        "abi_version": 1,
        "target": target,
        "source_fingerprint": binary.source_fingerprint(root),
        "artifacts": {
            library.name: {"size": len(payload), "sha256": hashlib.sha256(payload).hexdigest()}
        },
        "macos_deployment_target": "11.0",
        "libc": {"name": "glibc", "minimum_version": "2.28"},
        **metadata_fields,
    }
    (directory / binary.MANIFEST_NAME).write_text(json.dumps(metadata), encoding="utf-8")
    return library, metadata


@pytest.fixture
def packaging(monkeypatch, source_root):
    def forbid_process(*args, **kwargs):
        pytest.fail(f"A normal installation attempted an external command: {args!r}")

    monkeypatch.delenv("CINE_BUILD_RUST", raising=False)
    monkeypatch.setattr(subprocess, "run", forbid_process)
    monkeypatch.setattr(subprocess, "check_output", forbid_process)
    monkeypatch.setattr(setuptools, "setup", lambda **kwargs: None)
    namespace = runpy.run_path(str(PROJECT / "setup.py"))
    namespace["selected_binary"].__globals__["ROOT"] = source_root
    return namespace


@pytest.mark.parametrize(
    "target,tag,libc",
    [
        ("x86_64-pc-windows-msvc", "win_amd64", ("glibc", "2.35")),
        ("aarch64-pc-windows-msvc", "win_arm64", ("glibc", "2.35")),
        ("x86_64-apple-darwin", "macosx_11_0_x86_64", ("glibc", "2.35")),
        ("aarch64-apple-darwin", "macosx_11_0_arm64", ("glibc", "2.35")),
        ("x86_64-unknown-linux-gnu", "linux_x86_64", ("glibc", "2.35")),
        ("aarch64-unknown-linux-musl", "linux_aarch64", ("musl", "1.2.5")),
    ],
)
def test_default_packaging_copies_verified_library_without_compilers(
    packaging, source_root, tmp_path, monkeypatch, target, tag, libc
):
    binary = packaging["binary"]
    set_host(monkeypatch, binary, target, libc=libc)
    library, metadata = prebuilt(
        binary, source_root, target, libc={"name": libc[0], "minimum_version": libc[1]}
    )
    metadata["artifacts"]["cine-tool"] = {"size": 3, "sha256": hashlib.sha256(b"cli").hexdigest()}
    (library.parent / binary.MANIFEST_NAME).write_text(json.dumps(metadata), encoding="utf-8")
    assert packaging["selected_binary"]()[0] == library

    destination = tmp_path / "wheel" / "cine_reader" / "libs"
    destination.mkdir(parents=True)
    for stale in ("old.dll", "old.dylib", "old.so"):
        (destination / stale).write_bytes(b"stale native code")
    packaging["install_binary"](destination)
    assert (destination / library.name).read_bytes() == library.read_bytes()
    assert {path.name for path in destination.iterdir()} == {library.name, binary.MANIFEST_NAME}
    installed = json.loads((destination / binary.MANIFEST_NAME).read_text())
    assert installed["artifacts"] == {library.name: metadata["artifacts"][library.name]}

    wheel = packaging["RustWheel"](packaging["BinaryDistribution"]())
    wheel.plat_name_supplied = False
    assert wheel.get_tag() == ("py3", "none", tag)
    wheel.plat_name_supplied = True
    wheel.plat_name = "another_platform"
    with pytest.raises(RuntimeError, match="relabel"):
        wheel.get_tag()


def test_missing_prebuilt_never_falls_back_to_compilation(packaging, monkeypatch):
    binary = packaging["binary"]
    set_host(monkeypatch, binary, "x86_64-pc-windows-msvc")
    with pytest.raises(binary.BinaryError, match="prebuilt"):
        packaging["selected_binary"]()


@pytest.mark.parametrize("name", ["Cargo.toml", "rust/cine-core/src/lib.rs", ".cargo/config.toml"])
def test_native_source_changes_invalidate_prebuilt(binary, source_root, monkeypatch, name):
    target = "x86_64-pc-windows-msvc"
    set_host(monkeypatch, binary, target)
    prebuilt(binary, source_root, target)
    with (source_root / name).open("ab") as stream:
        stream.write(b"\n// Changed build input\n")
    with pytest.raises(binary.BinaryError, match="stale|fingerprint"):
        binary.select_prebuilt(source_root)


def test_git_crlf_checkout_and_directory_name_do_not_invalidate_fingerprint(
    binary, source_root, tmp_path
):
    checkout = tmp_path / "Windows checkout"
    shutil.copytree(source_root, checkout)
    for path in checkout.rglob("*"):
        if path.is_file():
            path.write_bytes(path.read_bytes().replace(b"\n", b"\r\n"))
    assert binary.source_fingerprint(checkout) == binary.source_fingerprint(source_root)


@pytest.mark.parametrize("missing", ["cine_core.dll", "build-info.json"])
def test_missing_binary_or_manifest_fails_closed(binary, source_root, monkeypatch, missing):
    target = "x86_64-pc-windows-msvc"
    set_host(monkeypatch, binary, target)
    library, _ = prebuilt(binary, source_root, target)
    (library.parent / missing).unlink()
    with pytest.raises(binary.BinaryError):
        binary.validate_library(library.parent, source_root)


@pytest.mark.parametrize(
    "field,value",
    [
        ("abi_version", 2),
        ("schema_version", True),
        ("target", "aarch64-pc-windows-msvc"),
        ("artifacts", []),
        ("source_fingerprint", "not-a-digest"),
    ],
)
def test_incompatible_or_malformed_manifest_fails_closed(
    binary, source_root, monkeypatch, field, value
):
    target = "x86_64-pc-windows-msvc"
    set_host(monkeypatch, binary, target)
    library, metadata = prebuilt(binary, source_root, target)
    metadata[field] = value
    (library.parent / binary.MANIFEST_NAME).write_text(json.dumps(metadata), encoding="utf-8")
    # Installed wheels have no source tree but must still validate their manifest.
    with pytest.raises(binary.BinaryError):
        binary.validate_library(library.parent)


@pytest.mark.parametrize("corruption", ["missing-checksum", "changed-bytes", "wrong-size"])
def test_artifact_integrity_is_required(binary, source_root, monkeypatch, corruption):
    target = "x86_64-pc-windows-msvc"
    set_host(monkeypatch, binary, target)
    library, metadata = prebuilt(binary, source_root, target)
    record = metadata["artifacts"][library.name]
    if corruption == "missing-checksum":
        del record["sha256"]
    elif corruption == "changed-bytes":
        data = bytearray(library.read_bytes())
        data[-1] ^= 1
        library.write_bytes(data)
    else:
        record["size"] += 1
    (library.parent / binary.MANIFEST_NAME).write_text(json.dumps(metadata), encoding="utf-8")
    with pytest.raises(binary.BinaryError):
        binary.validate_library(library.parent, source_root)


@pytest.mark.parametrize("suffix", ["pc-windows-msvc", "unknown-linux-gnu", "apple-darwin"])
def test_correct_checksum_cannot_hide_wrong_machine_header(
    binary, source_root, monkeypatch, suffix
):
    target = f"x86_64-{suffix}"
    set_host(monkeypatch, binary, target)
    library, _ = prebuilt(binary, source_root, target, payload=native_header(f"aarch64-{suffix}"))
    with pytest.raises(binary.BinaryError, match="architecture|processor"):
        binary.validate_library(library.parent, source_root)


@pytest.mark.parametrize(
    "libc_metadata",
    [
        {"name": "glibc", "minimum_version": "2.40"},
        {"name": "musl", "minimum_version": "1.2"},
        {"name": "glibc"},
        [],
    ],
)
def test_linux_libc_requirements_are_enforced(binary, source_root, monkeypatch, libc_metadata):
    target = "x86_64-unknown-linux-gnu"
    set_host(monkeypatch, binary, target, libc=("glibc", "2.35"))
    library, _ = prebuilt(binary, source_root, target, libc=libc_metadata)
    with pytest.raises(binary.BinaryError):
        binary.validate_library(library.parent, source_root)


@pytest.mark.parametrize(
    "actual_minimum,declared_minimum,host_version",
    [((12, 0, 0), "11.0", "14.0"), ((11, 0, 0), "12.0", "11.7"), ((10, 15, 0), "10.15", "14.0")],
)
def test_macos_binary_and_host_deployment_floors_are_enforced(
    binary, source_root, monkeypatch, actual_minimum, declared_minimum, host_version
):
    target = "aarch64-apple-darwin"
    set_host(monkeypatch, binary, target, version=host_version)
    library, _ = prebuilt(
        binary,
        source_root,
        target,
        payload=native_header(target, minimum=actual_minimum),
        macos_deployment_target=declared_minimum,
    )
    with pytest.raises(binary.BinaryError, match="macOS|deployment"):
        binary.validate_library(library.parent, source_root)
