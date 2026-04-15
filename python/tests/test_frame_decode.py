from __future__ import annotations

import numpy as np

from cine_reader.frame_decode import decode_frame_payload
from cine_reader.unpack import unpack_10bit_numpy


def _pack_group(v0: int, v1: int, v2: int, v3: int) -> bytes:
    v0, v1, v2, v3 = int(v0), int(v1), int(v2), int(v3)
    combined = (
        ((v0 & 0x3FF) << 30)
        | ((v1 & 0x3FF) << 20)
        | ((v2 & 0x3FF) << 10)
        | (v3 & 0x3FF)
    )
    return bytes(
        (
            (combined >> 32) & 0xFF,
            (combined >> 24) & 0xFF,
            (combined >> 16) & 0xFF,
            (combined >> 8) & 0xFF,
            combined & 0xFF,
        )
    )


def _pack_10bit(values: np.ndarray) -> bytes:
    flat = values.reshape(-1)
    if flat.size % 4 != 0:
        raise ValueError("test values must be a multiple of 4 samples")
    return b"".join(_pack_group(*flat[idx:idx + 4]) for idx in range(0, flat.size, 4))


def test_packed_10bit_decodes_raw_mosaic() -> None:
    codes = np.arange(16, dtype=np.uint16).reshape(4, 4)
    raw = _pack_10bit(codes)

    frame = decode_frame_payload(
        raw,
        bit_count=16,
        width=4,
        height_signed=4,
        real_bpp=10,
        unpack_10bit_fn=unpack_10bit_numpy,
    )

    assert frame.shape == (4, 4)
    assert frame.dtype == np.uint16
    assert frame[0, 0] == 2
    assert frame[-1, -1] == 18


def test_normal_16bit_decodes_raw_mosaic() -> None:
    raw_frame = np.arange(16, dtype=np.uint16).reshape(4, 4)

    frame = decode_frame_payload(
        raw_frame.tobytes(),
        bit_count=16,
        width=4,
        height_signed=4,
        real_bpp=12,
        unpack_10bit_fn=unpack_10bit_numpy,
    )

    assert frame.shape == (4, 4)
    assert frame.dtype == np.uint16
    assert np.array_equal(frame, raw_frame)
