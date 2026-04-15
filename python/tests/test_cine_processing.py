from __future__ import annotations

import numpy as np

from cine_reader import BitmapHeader, Cine, Setup


def _fake_color_cine(*, cfa: int = 4) -> Cine:
    cine = Cine.__new__(Cine)
    cine.image_header = BitmapHeader(
        ImageHeaderData=b"",
        biSize=40,
        biWidth=4,
        biHeight=4,
        biPlanes=1,
        biBitCount=16,
        biCompression=0,
        biSizeImage=0,
        biXPelsPerMeter=0,
        biYPelsPerMeter=0,
        biClrUsed=0,
        biClrImportant=0,
    )
    cine.camera_setup = Setup(
        SetupData=b"",
        RealBPP=12,
        bEnableColor=True,
        _extra={"CFA": cfa, "WhiteLevel": 4094},
    )
    cine.bayer_pattern_mode = "auto"
    cine.dead_value = None
    cine.dead_is_threshold = True
    cine.remove_dead_pixels = False
    cine.debayer = False
    cine.red_pixels = None
    cine.green_pixels = None
    cine.blue_pixels = None
    cine._pixel_array_channel_order = None
    cine._color_samples_from_raw_cfa = False
    return cine


def test_raw_cfa_sample_arrays_use_actual_color_sites() -> None:
    cine = _fake_color_cine(cfa=4)  # RGGB
    frame = np.arange(16, dtype=np.uint16).reshape(4, 4)

    cine._update_color_sample_arrays(frame)

    assert cine.red_pixels is not None
    assert cine.green_pixels is not None
    assert cine.blue_pixels is not None
    assert cine.red_pixels[0, 0] == 0
    assert np.isnan(cine.red_pixels[0, 1])
    assert cine.green_pixels[0, 1] == 1
    assert cine.green_pixels[1, 0] == 4
    assert np.isnan(cine.green_pixels[0, 0])
    assert cine.blue_pixels[1, 1] == 5
    assert np.isnan(cine.blue_pixels[0, 0])


def test_debayer_frame_mutates_current_raw_frame_to_rgb() -> None:
    cine = _fake_color_cine(cfa=4)  # RGGB
    cine.pixel_array = np.arange(16, dtype=np.uint16).reshape(4, 4)
    cine.pixel_data = cine.pixel_array.reshape(-1)

    cine.debayer_frame()

    assert cine.pixel_array.shape == (4, 4, 3)
    assert cine._pixel_array_channel_order == "RGB"
    assert cine.red_pixels is not None
    assert cine.red_pixels[0, 0] == 0
    assert np.isnan(cine.red_pixels[0, 1])
