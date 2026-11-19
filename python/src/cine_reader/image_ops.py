"""Thin NumPy adapters for Rust image processing."""
from __future__ import annotations

import numpy as np

from ._native import check, library

_BAYER_PHASE_ROLES = {
    "RGGB": ((0, 0, "R"), (0, 1, "G_R"), (1, 0, "G_B"), (1, 1, "B")),
    "BGGR": ((0, 0, "B"), (0, 1, "G_B"), (1, 0, "G_R"), (1, 1, "R")),
    "GRBG": ((0, 0, "G_R"), (0, 1, "R"), (1, 0, "B"), (1, 1, "G_B")),
    "GBRG": ((0, 0, "G_B"), (0, 1, "B"), (1, 0, "R"), (1, 1, "G_R")),
}


def _bayer_phase_roles(pattern: str) -> tuple[tuple[int, int, str], ...]:
    try:
        return _BAYER_PHASE_ROLES[pattern.upper()]
    except KeyError as exc:
        raise ValueError(f"Unsupported Bayer pattern: {pattern}") from exc


def _process(frame, op: int, param: int = 0, value: float = 0):
    original = np.asarray(frame)
    types = {np.dtype("uint8"): 1, np.dtype("uint16"): 2,
             np.dtype("float32"): 4, np.dtype("float64"): 8}
    dtype = original.dtype.newbyteorder("=")
    if dtype not in types:
        if dtype.kind not in "biuf":
            raise TypeError("Image data must be numeric")
        dtype = np.dtype("float64")
    source = np.ascontiguousarray(original, dtype=dtype)
    shape = source.shape + (3,) if op == 3 else source.shape
    result = np.empty(shape, dtype=dtype)
    if source.size:
        lib = library()
        check(lib.cine_process(source.ctypes.data, result.ctypes.data,
                               source.shape[1], source.shape[0],
                               source.shape[2] if source.ndim == 3 else 1,
                               types[dtype], op, param, value), lib)
    return result.astype(original.dtype, copy=False)


def replace_dead_pixels_mono(frame: np.ndarray, dead_value: int = 4095,
                             *, dead_is_threshold: bool = False) -> np.ndarray:
    """Replace dead mono samples with the valid 8-neighbor mean in Rust."""
    if frame.ndim != 2:
        return frame
    return _process(frame, 1, int(dead_is_threshold), float(dead_value))


def replace_dead_pixels_bayer(frame: np.ndarray, dead_value: int = 4095,
                              *, dead_is_threshold: bool = False) -> np.ndarray:
    """Repair each Bayer phase using neighbors of the same color phase."""
    if frame.ndim != 2:
        return frame
    return _process(frame, 2, int(dead_is_threshold), float(dead_value))


def replace_dead_pixels_rgb(frame: np.ndarray, dead_value: int = 4095,
                            *, dead_is_threshold: bool = False) -> np.ndarray:
    """Repair RGB/BGR samples independently within each channel."""
    if frame.ndim != 3:
        return frame
    if frame.shape[-1] <= 1:
        return frame.reshape(frame.shape[:2])
    return _process(frame, 1, int(dead_is_threshold), float(dead_value))


def replace_dead_pixels(frame: np.ndarray, *, dead_value: int = 4095,
                        dead_is_threshold: bool = False, bayer_raw: bool = False) -> np.ndarray:
    """Dispatch repair for mono, Bayer, and multichannel image arrays."""
    function = replace_dead_pixels_rgb if frame.ndim == 3 else (
        replace_dead_pixels_bayer if frame.ndim == 2 and bayer_raw else replace_dead_pixels_mono
    )
    return function(frame, dead_value, dead_is_threshold=dead_is_threshold)


def demosaic_bilinear(frame: np.ndarray, pattern: str = "RGGB") -> np.ndarray:
    """Bilinear demosaic with clamped borders and the existing rounding rules."""
    if frame.ndim != 2:
        raise ValueError("Bayer input must be a two-dimensional array")
    token = pattern.upper()
    _bayer_phase_roles(token)
    return _process(frame, 3, ("RGGB", "BGGR", "GRBG", "GBRG").index(token))
