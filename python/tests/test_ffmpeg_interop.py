"""Independent CINE container/pixel verification through FFmpeg when installed."""
from __future__ import annotations

import shutil
import subprocess

import numpy as np
import pytest

from cine_reader import write_cine
from cine_reader._lookup import LOOKUP_TABLE


FFMPEG = shutil.which("ffmpeg")
pytestmark = pytest.mark.skipif(FFMPEG is None, reason="FFmpeg is not installed")


def decode_with_ffmpeg(path, pixel_format):
    completed = subprocess.run(
        [FFMPEG, "-v", "error", "-i", str(path), "-vsync", "0", "-f", "rawvideo",
         "-pix_fmt", pixel_format, "pipe:1"],
        check=True, capture_output=True,
    )
    return completed.stdout


@pytest.mark.parametrize("width", [5, 64])
@pytest.mark.parametrize("dtype,channels,pixel_format", [
    (np.uint8, 1, "gray"),
    (np.uint16, 1, "gray16le"),
    (np.uint8, 3, "rgb24"),
    (np.uint16, 3, "rgb48le"),
])
def test_ffmpeg_recovers_normal_pixels_exactly(tmp_path, width, dtype, channels, pixel_format):
    shape = (3, 4, width) + ((3,) if channels == 3 else ())
    frames = np.random.default_rng(431).integers(
        0, np.iinfo(dtype).max + 1, size=shape, dtype=dtype,
    )
    path = tmp_path / "normal.cine"
    write_cine(path, frames, first_frame=-1, frame_rate=30)
    assert decode_with_ffmpeg(path, pixel_format) == frames.tobytes()


@pytest.mark.parametrize("width", [5, 64])
@pytest.mark.parametrize("channels,pixel_format", [(1, "gray16le"), (3, "bayer_rggb16le")])
def test_ffmpeg_recovers_phantom_packed_codes(tmp_path, width, channels, pixel_format):
    shape = (2, 3, width) + ((3,) if channels == 3 else ())
    indices = (np.arange(np.prod(shape)) * 37 % 1024).reshape(shape)
    frames = LOOKUP_TABLE[indices]
    path = tmp_path / "packed.cine"
    write_cine(path, frames, encoding="packed10")
    if channels == 1:
        mosaic = frames
    else:
        mosaic = np.empty(frames.shape[:3], dtype=np.uint16)
        for row, col, channel in [(0, 0, 0), (0, 1, 1), (1, 0, 1), (1, 1, 2)]:
            mosaic[:, row::2, col::2] = frames[:, row::2, col::2, channel]
    codes = np.searchsorted(LOOKUP_TABLE, mosaic, side="left").astype(np.uint16)
    # FFmpeg expands P10 code bits to 16 bits; it does not apply the Phantom LUT.
    expected = ((codes << 6) | (codes >> 4)).astype("<u2")
    assert decode_with_ffmpeg(path, pixel_format) == expected.tobytes()
