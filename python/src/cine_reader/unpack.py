"""Packed 10-bit helpers backed by the shared Rust decoder."""

from __future__ import annotations

import numpy as np

from ._lookup import LOOKUP_TABLE
from ._native import check, library


def unpack_10bit_data(data: bytes) -> np.ndarray:
    """Expand complete groups of four Phantom packed10 samples to linear uint16."""
    payload = np.frombuffer(data, dtype=np.uint8)
    samples = payload.size // 5 * 4
    result = np.empty(samples, dtype=np.uint16)
    if samples:
        lib = library()
        check(
            lib.cine_unpack10(payload.ctypes.data, samples // 4 * 5, result.ctypes.data, samples),
            lib,
        )
    return result


def unpack_10bit_numpy(data: bytes) -> np.ndarray:
    """Explicit NumPy reference implementation; normal decoding uses Rust."""
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
