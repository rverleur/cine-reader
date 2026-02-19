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
        assert cine.file_header is not None
        assert cine.image_header is not None
        assert cine.camera_setup is not None

        assert cine.total_frames > 0
        assert cine.image_header.biWidth > 0
        assert abs(cine.image_header.biHeight) > 0
        assert cine.image.size > 0

        first = cine.first_frame_number
        last = first + min(4, cine.total_frames - 1)
        cine.load_frame(first)
        assert cine.frame.ndim in (2, 3)

        avg = cine.average_frames(first, last)
        assert avg.shape == cine.frame.shape

        mode_mad = cine.mode_frames(first, last, method="mad")
        mode_topk = cine.mode_frames(first, last, method="topk")
        assert mode_mad.shape == cine.frame.shape
        assert mode_topk.shape == cine.frame.shape

        assert cine.last_frame_number >= cine.first_frame_number
        assert cine.frame_rate >= 0.0
        assert cine.exposure_time >= 0.0
    finally:
        cine.close_file()
