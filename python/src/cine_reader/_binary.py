"""Validate prebuilt backends using only Python's standard library.

This module is also loaded directly by setup.py, before NumPy is installed.
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import struct
from pathlib import Path

ABI_VERSION = 1
MANIFEST_NAME = "build-info.json"


class BinaryError(RuntimeError):
    """A matching, verified native backend is unavailable."""


def linux_libc() -> tuple[str, str]:
    """Identify libc without invoking ldd, a shell, or any external program."""
    try:
        name, version = os.confstr("CS_GNU_LIBC_VERSION").split()
        if name == "glibc":
            return name, version
    except (AttributeError, OSError, TypeError, ValueError):
        pass
    name, version = platform.libc_ver()
    if name in ("glibc", "musl"):
        return name, version
    if any(Path("/lib").glob("ld-musl-*.so.1")):
        return "musl", ""
    raise BinaryError(
        "Cannot identify Linux libc; refusing to select a possibly incompatible binary."
    )


def host_target() -> str:
    machine = platform.machine().lower()
    machine = {"amd64": "x86_64", "arm64": "aarch64"}.get(machine, machine)
    if struct.calcsize("P") != 8 or machine not in ("x86_64", "aarch64"):
        raise BinaryError(f"No prebuilt CINE backend supports this Python architecture: {machine}.")
    system = platform.system()
    if system == "Darwin":
        return f"{machine}-apple-darwin"
    if system == "Windows":
        return f"{machine}-pc-windows-msvc"
    if system == "Linux":
        name, _ = linux_libc()
        return f"{machine}-unknown-linux-{'gnu' if name == 'glibc' else 'musl'}"
    raise BinaryError(f"No prebuilt CINE backend supports {system}.")


def library_name(target: str) -> str:
    if target.endswith("-apple-darwin"):
        return "libcine_core.dylib"
    if target.endswith("-pc-windows-msvc"):
        return "cine_core.dll"
    if target.endswith(("-unknown-linux-gnu", "-unknown-linux-musl")):
        return "libcine_core.so"
    raise BinaryError(f"Unsupported native target: {target}.")


def file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def source_fingerprint(root: Path) -> str:
    """Hash portable build inputs, independent of checkout paths and CRLF conversion."""
    required = ("Cargo.toml", "Cargo.lock", "rust/cine-core/Cargo.toml")
    files = {root / name for name in required}
    for name in ("rust/cine-core/src", "rust/cine-core/include"):
        directory = root / name
        if not directory.is_dir():
            raise BinaryError(f"Cannot validate prebuilt backend: missing source directory {name}.")
        files.update(path for path in directory.rglob("*") if path.is_file())
    for name in (
        "rust/cine-core/build.rs",
        "rust-toolchain",
        "rust-toolchain.toml",
        ".cargo/config",
        ".cargo/config.toml",
    ):
        if (root / name).is_file():
            files.add(root / name)
    digest = hashlib.sha256()
    for path in sorted(files, key=lambda item: item.relative_to(root).as_posix()):
        try:
            data = path.read_bytes()
        except OSError as error:
            raise BinaryError(f"Cannot validate native source input {path}: {error}") from error
        if path.suffix in (".rs", ".h", ".toml", ".lock") or path.name in (
            "config",
            "rust-toolchain",
        ):
            data = data.replace(b"\r\n", b"\n")
        digest.update(path.relative_to(root).as_posix().encode("utf-8") + b"\0")
        digest.update(len(data).to_bytes(8, "big"))
        digest.update(data)
    return digest.hexdigest()


def version_tuple(value: str) -> tuple[int, ...]:
    if not isinstance(value, str) or not re.fullmatch(r"\d+\.\d+(?:\.\d+)?", value):
        raise BinaryError(f"Invalid native compatibility version: {value!r}.")
    parts = tuple(int(part) for part in value.split("."))
    return parts + (0,) * (3 - len(parts))


def _native_header(path: Path, target: str) -> tuple[int, ...] | None:
    """Check machine headers and read a Mach-O deployment minimum without tools."""
    arm = target.startswith("aarch64-")
    with path.open("rb") as stream:
        header = stream.read(64)
        if target.endswith("-apple-darwin"):
            cpu = 0x0100000C if arm else 0x01000007
            if len(header) < 32 or header[:4] != b"\xcf\xfa\xed\xfe":
                raise BinaryError(f"{path.name} is not a native 64-bit Mach-O library.")
            if struct.unpack_from("<I", header, 4)[0] != cpu:
                raise BinaryError(f"{path.name} has the wrong processor architecture.")
            commands, command_bytes = struct.unpack_from("<II", header, 16)
            if command_bytes > path.stat().st_size - 32:
                raise BinaryError("Malformed Mach-O load commands.")
            stream.seek(32)
            commands_data = stream.read(command_bytes)
            position = 0
            minimum = None
            for _ in range(commands):
                if position + 8 > len(commands_data):
                    raise BinaryError("Malformed Mach-O load command.")
                command, size = struct.unpack_from("<II", commands_data, position)
                if size < 8 or position + size > len(commands_data):
                    raise BinaryError("Malformed Mach-O load command size.")
                if command in (0x24, 0x32):  # LC_VERSION_MIN_MACOSX / LC_BUILD_VERSION
                    offset = 8 if command == 0x24 else 12
                    if size < offset + 4:
                        raise BinaryError("Malformed Mach-O deployment version.")
                    if (
                        command == 0x32
                        and struct.unpack_from("<I", commands_data, position + 8)[0] != 1
                    ):
                        raise BinaryError(
                            "Mach-O library targets an Apple platform other than macOS."
                        )
                    value = struct.unpack_from("<I", commands_data, position + offset)[0]
                    minimum = (value >> 16, (value >> 8) & 255, value & 255)
                position += size
            if minimum is None:
                raise BinaryError("Mach-O library does not declare a deployment minimum.")
            return minimum
        if "-windows-" in target:
            if len(header) < 64 or header[:2] != b"MZ":
                raise BinaryError(f"{path.name} is not a Windows PE library.")
            stream.seek(struct.unpack_from("<I", header, 60)[0])
            pe = stream.read(6)
            if len(pe) != 6 or pe[:4] != b"PE\0\0":
                raise BinaryError("Malformed Windows PE header.")
            machine = struct.unpack_from("<H", pe, 4)[0]
            expected = 0xAA64 if arm else 0x8664
        else:
            if len(header) < 20 or header[:6] != b"\x7fELF\x02\x01":
                raise BinaryError(f"{path.name} is not a 64-bit little-endian ELF library.")
            machine = struct.unpack_from("<H", header, 18)[0]
            expected = 183 if arm else 62
        if machine != expected:
            raise BinaryError(f"{path.name} has the wrong processor architecture.")
    return None


def validate_library(directory: Path, root: Path | None = None) -> tuple[Path, dict]:
    target = host_target()
    try:
        metadata = json.loads((directory / MANIFEST_NAME).read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise BinaryError(
            f"Missing or invalid prebuilt manifest in {directory}: {error}"
        ) from error
    if (
        not isinstance(metadata, dict)
        or type(metadata.get("schema_version")) is not int
        or metadata["schema_version"] != 1
    ):
        raise BinaryError("Unsupported prebuilt manifest schema.")
    if metadata.get("target") != target:
        raise BinaryError(f"Prebuilt backend target does not match {target}.")
    if type(metadata.get("abi_version")) is not int or metadata["abi_version"] != ABI_VERSION:
        raise BinaryError("Prebuilt backend ABI does not match this Python interface.")
    fingerprint = metadata.get("source_fingerprint")
    if not isinstance(fingerprint, str) or not re.fullmatch(r"[0-9a-f]{64}", fingerprint):
        raise BinaryError("Prebuilt backend has an invalid Rust source fingerprint.")
    if root is not None and metadata.get("source_fingerprint") != source_fingerprint(root):
        raise BinaryError("Prebuilt backend is stale: its Rust source fingerprint does not match.")
    path = directory / library_name(target)
    artifacts = metadata.get("artifacts")
    if not isinstance(artifacts, dict):
        raise BinaryError("Prebuilt manifest artifacts must be a mapping.")
    record = artifacts.get(path.name)
    if not isinstance(record, dict):
        raise BinaryError(f"Prebuilt manifest does not describe {path.name}.")
    if not path.is_file() or path.stat().st_size != record.get("size"):
        raise BinaryError(f"Prebuilt library is missing or has an incorrect size: {path}.")
    if file_digest(path) != record.get("sha256"):
        raise BinaryError(f"Prebuilt library checksum mismatch: {path}.")
    minimum = _native_header(path, target)
    if minimum is not None:
        declared = version_tuple(metadata.get("macos_deployment_target"))
        if declared < minimum or (target.startswith("aarch64-") and declared < (11, 0, 0)):
            raise BinaryError("Prebuilt manifest understates the macOS deployment minimum.")
        if version_tuple(platform.mac_ver()[0]) < declared:
            raise BinaryError("This prebuilt backend requires a newer macOS version.")
    if "-linux-" in target:
        actual_name, actual_version = linux_libc()
        compatibility = metadata.get("libc")
        if not isinstance(compatibility, dict) or compatibility.get("name") != actual_name:
            raise BinaryError("Prebuilt backend uses a different Linux libc.")
        required = compatibility.get("minimum_version")
        if required:
            if not actual_version or version_tuple(actual_version) < version_tuple(required):
                raise BinaryError(f"This backend requires {actual_name} {required} or newer.")
        else:
            raise BinaryError("Linux backend is missing its minimum libc version.")
    return path, metadata


def select_prebuilt(root: Path) -> tuple[Path, dict]:
    directory = root / "binaries" / host_target()
    try:
        return validate_library(directory, root)
    except BinaryError as error:
        raise BinaryError(
            f"{error} Install a matching cine-handler wheel or obtain a checkout containing "
            f"a current prebuilt backend in {directory}. Maintainers can explicitly set "
            "CINE_BUILD_RUST=1 to compile during installation."
        ) from error


def check_build_environment(root: Path) -> None:
    forbidden = (
        "CARGO_BUILD_TARGET",
        "RUSTFLAGS",
        "CARGO_ENCODED_RUSTFLAGS",
        "RUSTC",
        "RUSTC_WRAPPER",
        "RUSTC_WORKSPACE_WRAPPER",
    )
    if any(os.environ.get(key) for key in forbidden) or any(
        key.startswith("CARGO_TARGET_") and key.endswith("_RUSTFLAGS") and value
        for key, value in os.environ.items()
    ):
        raise BinaryError(
            "Native distributable builds require default Rust compiler/CPU/target settings."
        )
    directories = [root, *root.parents]
    configs = [
        parent / ".cargo" / name for parent in directories for name in ("config", "config.toml")
    ]
    cargo_home = Path(os.environ.get("CARGO_HOME", str(Path.home() / ".cargo")))
    configs.extend(cargo_home / name for name in ("config", "config.toml"))
    for config in configs:
        if not config.is_file():
            continue
        settings = re.sub(r"(?m)#.*$", "", config.read_text(encoding="utf-8"))
        # This checked-in setting links the Windows C runtime statically; it
        # introduces no CPU instruction requirement and makes wheels standalone.
        if config.resolve() == (root / ".cargo/config.toml").resolve():
            settings = re.sub(
                r"(?m)^\s*\[target\.(?:x86_64|aarch64)-pc-windows-msvc\]\s*"
                r'rustflags\s*=\s*\[\s*"-C"\s*,\s*"target-feature=\+crt-static"\s*\]',
                "",
                settings,
            )
        if re.search(
            r"(?m)^\s*(?:target|rustflags|rustc-wrapper|rustc-workspace-wrapper)\s*=", settings
        ):
            raise BinaryError(
                f"Custom Rust target/compiler flags in {config} require a separate build."
            )


def make_manifest(root: Path, target: str, files: list[Path], **provenance) -> dict:
    metadata = {
        "schema_version": 1,
        "abi_version": ABI_VERSION,
        "target": target,
        "source_fingerprint": source_fingerprint(root),
        "artifacts": {
            path.name: {"size": path.stat().st_size, "sha256": file_digest(path)} for path in files
        },
        **provenance,
    }
    if target.endswith("-apple-darwin"):
        metadata["macos_deployment_target"] = os.environ.get("MACOSX_DEPLOYMENT_TARGET", "11.0")
    if "-linux-" in target:
        name, version = linux_libc()
        if not version:
            raise BinaryError(
                "Cannot record a portable Linux build without identifying libc's version."
            )
        metadata["libc"] = {"name": name, "minimum_version": version}
    return metadata
