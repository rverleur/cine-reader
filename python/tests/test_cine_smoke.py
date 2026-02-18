from __future__ import annotations

from pathlib import Path

import pytest

from cine_reader import Cine


@pytest.mark.smoke
def test_open_sample_cine_if_available() -> None:
    sample = Path(__file__).resolve().parents[2] / "sample_data" / "TrimmedCine.cine"
    if not sample.exists():
        pytest.skip("sample_data/TrimmedCine.cine not present")

    cine = Cine(sample)
    try:
        assert cine.FileHeader.ImageCount > 0
        assert cine.ImageHeader.biWidth > 0
        assert abs(cine.ImageHeader.biHeight) > 0
        assert cine.PixelArray.size > 0

        first = cine.FileHeader.FirstImageNo
        last = first + min(4, cine.FileHeader.ImageCount - 1)
        cine.LoadFrame(first)
        assert cine.PixelArray.ndim in (2, 3)

        avg = cine.AverageFrames(first, last)
        assert avg.shape == cine.PixelArray.shape

        if cine.PixelArray.ndim == 2:
            mode_mad = cine.ModeFrames(first, last, method="mad")
            mode_topk = cine.ModeFrames(first, last, method="topk")
            assert mode_mad.shape == cine.PixelArray.shape
            assert mode_topk.shape == cine.PixelArray.shape
    finally:
        cine.CloseFile()
