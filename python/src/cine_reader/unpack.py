"""Packed 10-bit Phantom unpack helpers."""

from __future__ import annotations

import ctypes
import os
import platform
from dataclasses import dataclass
from importlib import resources
from typing import Optional

import numpy as np

from ._lookup import LOOKUP_TABLE


@dataclass(frozen=True)
class _LibrarySpec:
    filename: str
    symbol: str


_LIB_CACHE: dict[str, object] = {
    "loaded": False,
    "lib": None,
    "symbol": None,
    "error": None,
}


def _platform_spec() -> Optional[_LibrarySpec]:
    system = platform.system()
    arch = platform.architecture()[0]
    if system == "Windows":
        if arch == "64bit":
            return _LibrarySpec("unpack_data_win64.dll", "unpack_data_win64")
        return _LibrarySpec("unpack_data_win32.dll", "unpack_data_win32")
    if system == "Darwin":
        return _LibrarySpec("unpack_data_arm64.dylib", "unpack_data_arm64")
    if system == "Linux":
        return _LibrarySpec("unpack_data_elf64.so", "unpack_data_elf64")
    return None


def _try_load_library() -> tuple[Optional[ctypes.CDLL], Optional[str]]:
    if _LIB_CACHE["loaded"]:
        return _LIB_CACHE["lib"], _LIB_CACHE["symbol"]

    spec = _platform_spec()
    if spec is None:
        _LIB_CACHE.update(loaded=True, lib=None, symbol=None, error="unsupported platform")
        return None, None

    try:
        package_lib = resources.files("cine_reader").joinpath("libs", spec.filename)
        if not package_lib.is_file():
            _LIB_CACHE.update(loaded=True, lib=None, symbol=None, error="library file not found")
            return None, None
        with resources.as_file(package_lib) as lib_path:
            lib = ctypes.CDLL(str(lib_path))

        unpack_fn = getattr(lib, spec.symbol)
        unpack_fn.argtypes = [
            ctypes.POINTER(ctypes.c_uint8),
            ctypes.c_size_t,
            ctypes.POINTER(ctypes.c_size_t),
        ]
        unpack_fn.restype = ctypes.POINTER(ctypes.c_uint16)

        lib.free_pixel_data.argtypes = [ctypes.POINTER(ctypes.c_uint16)]
        lib.free_pixel_data.restype = None

        _LIB_CACHE.update(loaded=True, lib=lib, symbol=spec.symbol, error=None)
        return lib, spec.symbol
    except Exception as exc:  # pragma: no cover - platform dependent
        _LIB_CACHE.update(loaded=True, lib=None, symbol=None, error=str(exc))
        return None, None


def unpack_10bit_numpy(data: bytes) -> np.ndarray:
    """Decode packed 10-bit payload with NumPy and the C-equivalent lookup table."""
    byte_data = np.frombuffer(data, dtype=np.uint8)
    groups = byte_data.size // 5
    if groups == 0:
        return np.empty(0, dtype=np.uint16)

    packed = byte_data[: groups * 5].reshape(groups, 5).astype(np.uint64, copy=False)
    combined = (
        (packed[:, 0] << 32)
        | (packed[:, 1] << 24)
        | (packed[:, 2] << 16)
        | (packed[:, 3] << 8)
        | packed[:, 4]
    )

    idx0 = (combined >> 30) & 0x3FF
    idx1 = (combined >> 20) & 0x3FF
    idx2 = (combined >> 10) & 0x3FF
    idx3 = combined & 0x3FF

    out = np.empty(groups * 4, dtype=np.uint16)
    out[0::4] = LOOKUP_TABLE[idx0]
    out[1::4] = LOOKUP_TABLE[idx1]
    out[2::4] = LOOKUP_TABLE[idx2]
    out[3::4] = LOOKUP_TABLE[idx3]
    return out


def _unpack_10bit_c(data: bytes) -> Optional[np.ndarray]:
    if os.environ.get("CINE_READER_DISABLE_C_UNPACK", "0") == "1":
        return None

    lib, symbol = _try_load_library()
    if lib is None or symbol is None:
        return None

    unpack_fn = getattr(lib, symbol)
    payload = np.frombuffer(data, dtype=np.uint8)
    num_pixels = ctypes.c_size_t()
    ptr = unpack_fn(
        payload.ctypes.data_as(ctypes.POINTER(ctypes.c_uint8)),
        ctypes.c_size_t(payload.size),
        ctypes.byref(num_pixels),
    )
    if not ptr:
        raise RuntimeError("C unpack routine returned NULL")

    try:
        return np.ctypeslib.as_array(ptr, shape=(num_pixels.value,)).copy()
    finally:
        lib.free_pixel_data(ptr)


def unpack_10bit_data(data: bytes) -> np.ndarray:
    """Decode packed 10-bit payload using C library when available."""
    decoded = _unpack_10bit_c(data)
    if decoded is not None:
        return decoded
    return unpack_10bit_numpy(data)
