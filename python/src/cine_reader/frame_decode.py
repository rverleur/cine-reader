"""Compatibility wrapper around Rust's standalone frame decoder."""
from __future__ import annotations

import numpy as np

from ._native import check, library


def decode_frame_payload(
    raw: bytes,
    *,
    bit_count: int,
    width: int,
    height_signed: int,
    real_bpp: int,
    unpack_10bit_fn,
    compression: int | None = None,
) -> np.ndarray:
    """Decode a payload in legacy storage-row/BGR order.

    Supply bitmap ``compression`` when available (0 normal, 256 packed10,
    1024 packed12). Older callers omit it; packed10 is then recognized from
    its payload length as well as RealBPP, so normal 10-bit-in-16-bit data is
    decoded correctly. The historical packed decoder callback is preserved.
    """
    if bit_count not in (8, 16, 24, 48) or width <= 0 or height_signed == 0:
        raise ValueError("Unsupported bit depth or image dimensions")
    channels = 1 if bit_count in (8, 16) else 3
    height = abs(int(height_signed))
    samples = height * int(width) * channels
    if compression is None:
        compression = 256 if real_bpp == 10 and len(raw) == ((samples + 3) // 4) * 5 else 0
    shape = (height, int(width)) + (() if channels == 1 else (3,))
    if compression == 256 and unpack_10bit_fn is not None:
        output = unpack_10bit_fn(raw)
        if output.size < samples:
            raise ValueError("Packed 10-bit decode returned too few samples")
        return output[:samples].reshape(shape)
    output = np.empty(shape, dtype=np.uint8 if bit_count in (8, 24) else "<u2")
    payload = np.frombuffer(raw, dtype=np.uint8)
    lib = library()
    check(lib.cine_decode(payload.ctypes.data, payload.nbytes, width, height_signed,
                          bit_count, compression, 0, output.ctypes.data, output.nbytes), lib)
    return output
