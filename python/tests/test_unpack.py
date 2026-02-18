from __future__ import annotations

import numpy as np

from cine_reader._lookup import LOOKUP_TABLE
from cine_reader.unpack import unpack_10bit_data, unpack_10bit_numpy


def _pack_group(v0: int, v1: int, v2: int, v3: int) -> bytes:
    combined = ((v0 & 0x3FF) << 30) | ((v1 & 0x3FF) << 20) | ((v2 & 0x3FF) << 10) | (v3 & 0x3FF)
    return bytes(
        (
            (combined >> 32) & 0xFF,
            (combined >> 24) & 0xFF,
            (combined >> 16) & 0xFF,
            (combined >> 8) & 0xFF,
            combined & 0xFF,
        )
    )


def test_unpack_numpy_matches_lookup_table() -> None:
    codes = np.array([0, 1, 2, 3, 10, 100, 500, 1023], dtype=np.uint16)
    raw = _pack_group(*codes[:4]) + _pack_group(*codes[4:8])

    out = unpack_10bit_numpy(raw)
    expected = LOOKUP_TABLE[codes]

    assert out.dtype == np.uint16
    assert np.array_equal(out, expected)


def test_unpack_dispatch_matches_numpy() -> None:
    codes = np.array([7, 9, 123, 1022], dtype=np.uint16)
    raw = _pack_group(*codes)

    out_dispatch = unpack_10bit_data(raw)
    out_numpy = unpack_10bit_numpy(raw)

    assert np.array_equal(out_dispatch, out_numpy)
