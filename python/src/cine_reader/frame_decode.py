"""Frame payload decoding helpers for Phantom CINE data."""

from __future__ import annotations

import numpy as np


def decode_frame_payload(
    raw: bytes,
    *,
    bit_count: int,
    width: int,
    height_signed: int,
    real_bpp: int,
    unpack_10bit_fn,
) -> np.ndarray:
    """Decode one frame payload to a NumPy array.

    Parameters
    ----------
    raw:
        Raw frame payload bytes (annotation block excluded).
    bit_count:
        Container bit depth from bitmap header (`biBitCount`).
    width:
        Image width.
    height_signed:
        Signed image height from bitmap header. Negative means top-down storage.
    real_bpp:
        Sensor bit depth from setup block (`RealBPP`).
    unpack_10bit_fn:
        Callable that decodes Phantom packed 10-bit blocks to `uint16`.

    Returns
    -------
    numpy.ndarray
        Decoded frame payload. Raw CFA color frames remain 2D sensor mosaics;
        debayering is handled by `Cine`.
    """
    height = abs(int(height_signed))
    channels = 1 if bit_count in (8, 16) else 3

    if bit_count in (8, 24):
        row_bytes = width * channels
        row_stride = ((row_bytes + 3) // 4) * 4
        buffer_u8 = np.frombuffer(raw, dtype=np.uint8)
        if buffer_u8.size == height * row_stride:
            rows = buffer_u8.reshape(height, row_stride)[:, :row_bytes]
        elif buffer_u8.size == height * row_bytes:
            rows = buffer_u8.reshape(height, row_bytes)
        else:
            raise ValueError(
                f"8/24-bit size mismatch: got {buffer_u8.size}, expected "
                f"{height * row_bytes} or {height * row_stride}"
            )
        if channels == 1:
            return rows.reshape(height, width).copy()
        return rows.reshape(height, width, channels).copy()

    if bit_count not in (16, 48):
        raise ValueError(f"Unsupported bit depth: {bit_count}")

    if int(real_bpp) == 10:
        unpacked = unpack_10bit_fn(raw)
        expected = height * width * channels
        if unpacked.size < expected:
            raise ValueError(
                f"Packed 10-bit decode returned {unpacked.size} samples, expected at least {expected}"
            )
        unpacked = unpacked[:expected]
        if channels == 1:
            return unpacked.reshape(height, width)
        return unpacked.reshape(height, width, channels)

    row_bytes = width * channels * 2
    row_stride = ((row_bytes + 3) // 4) * 4
    buffer_u8 = np.frombuffer(raw, dtype=np.uint8)
    if buffer_u8.size == height * row_stride:
        rows_u8 = buffer_u8.reshape(height, row_stride)[:, :row_bytes]
    elif buffer_u8.size == height * row_bytes:
        rows_u8 = buffer_u8.reshape(height, row_bytes)
    else:
        raise ValueError(
            f"16/48-bit size mismatch: got {buffer_u8.size}, expected "
            f"{height * row_bytes} or {height * row_stride}"
        )
    rows_u8 = np.ascontiguousarray(rows_u8)
    values = rows_u8.view("<u2")
    if channels == 1:
        return values.reshape(height, width)
    return values.reshape(height, width, channels)
