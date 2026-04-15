from __future__ import annotations

import numpy as np

from cine_reader.image_ops import (
    demosaic_bilinear,
    replace_dead_pixels,
    replace_dead_pixels_bayer,
    replace_dead_pixels_mono,
    replace_dead_pixels_rgb,
)


def test_replace_dead_pixels_mono_replaces_exact_value() -> None:
    frame = np.array(
        [
            [10, 10, 10],
            [10, 4095, 10],
            [10, 10, 10],
        ],
        dtype=np.uint16,
    )
    out = replace_dead_pixels_mono(frame, dead_value=4095)
    assert out[1, 1] == 10
    assert out.dtype == np.uint16


def test_replace_dead_pixels_bayer_repairs_by_phase() -> None:
    frame = np.zeros((6, 6), dtype=np.uint16)
    frame[0::2, 0::2] = 10
    frame[0::2, 1::2] = 20
    frame[1::2, 0::2] = 30
    frame[1::2, 1::2] = 40
    frame[2, 2] = 4095

    out = replace_dead_pixels_bayer(frame, dead_value=4095)
    assert out[2, 2] == 10
    assert out[2, 3] == 20
    assert out[3, 2] == 30
    assert out[3, 3] == 40


def test_replace_dead_pixels_rgb_repairs_per_channel() -> None:
    frame = np.zeros((3, 3, 3), dtype=np.uint16)
    frame[..., 0] = 10
    frame[..., 1] = 20
    frame[..., 2] = 30
    frame[1, 1, 0] = 4095
    frame[0, 2, 2] = 4095

    out = replace_dead_pixels_rgb(frame, dead_value=4095)
    assert out[1, 1, 0] == 10
    assert out[0, 2, 2] == 30
    assert np.all(out[..., 1] == 20)


def test_replace_dead_pixels_dispatch_handles_bayer_and_rgb() -> None:
    mono_bayer = np.array(
        [
            [10, 20, 10, 20],
            [30, 40, 30, 40],
            [10, 20, 4095, 20],
            [30, 40, 30, 40],
        ],
        dtype=np.uint16,
    )
    out_bayer = replace_dead_pixels(mono_bayer, dead_value=4095, bayer_raw=True)
    assert out_bayer[2, 2] == 10

    rgb = np.zeros((2, 2, 3), dtype=np.uint16)
    rgb[..., 0] = 11
    rgb[..., 1] = 22
    rgb[..., 2] = 33
    rgb[0, 0, 1] = 4095
    out_rgb = replace_dead_pixels(rgb, dead_value=4095)
    assert out_rgb[0, 0, 1] == 22


def test_demosaic_bilinear_preserves_known_bayer_sites() -> None:
    frame = np.arange(35, dtype=np.uint16).reshape(5, 7)
    roles = {
        "RGGB": ((0, 0, 0), (0, 1, 1), (1, 0, 1), (1, 1, 2)),
        "BGGR": ((0, 0, 2), (0, 1, 1), (1, 0, 1), (1, 1, 0)),
        "GRBG": ((0, 0, 1), (0, 1, 0), (1, 0, 2), (1, 1, 1)),
        "GBRG": ((0, 0, 1), (0, 1, 2), (1, 0, 0), (1, 1, 1)),
    }

    for pattern, phase_channels in roles.items():
        rgb = demosaic_bilinear(frame, pattern)
        assert rgb.shape == frame.shape + (3,)
        assert rgb.dtype == frame.dtype
        for row_phase, col_phase, channel in phase_channels:
            assert np.array_equal(
                rgb[row_phase::2, col_phase::2, channel],
                frame[row_phase::2, col_phase::2],
            )
