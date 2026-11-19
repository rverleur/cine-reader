"""Round trips exercise the public API through the shared Rust ABI."""

from __future__ import annotations

import shutil
import subprocess

import numpy as np
import pytest

from cine_reader import Cine, CineWriter, write_cine, write_cine_from_images, write_cine_from_video
from cine_reader._lookup import LOOKUP_TABLE


@pytest.mark.parametrize(
    "dtype,channels", [(np.uint8, 1), (np.uint16, 1), (np.uint8, 3), (np.uint16, 3)]
)
def test_normal_roundtrip_padding_orientation_and_rgb(tmp_path, dtype, channels):
    shape = (3, 5) + (() if channels == 1 else (3,))
    frames = np.arange(3 * np.prod(shape), dtype=dtype).reshape((3,) + shape)
    output = write_cine(tmp_path / "normal.cine", frames, frame_rate=123.5, first_frame=-2)
    with Cine(output, canonical=True) as cine:
        assert cine._pending_frame
        assert cine.total_frames == 3
        assert cine.first_frame_number == -2
        assert cine.frame_rate == pytest.approx(123.5)
        assert np.array_equal(cine.image, frames[0])
        held = cine.image
        for index, expected in enumerate(frames):
            cine.load_frame(index - 2)
            assert np.array_equal(cine.image, expected)
        assert np.array_equal(held, frames[0])
    with Cine(output) as cine:
        expected = frames[0, ::-1]
        if channels == 3:
            expected = expected[..., ::-1]
        assert np.array_equal(cine.image, expected)


def test_unknown_length_stream_and_packed10(tmp_path):
    # Values already in Phantom's LUT must round-trip exactly (including endpoints).
    first = LOOKUP_TABLE[np.array([0, 1, 128, 255, 400, 512, 800, 1023])].reshape(2, 4)
    frames = (first.copy() for _ in range(4))
    output = write_cine(tmp_path / "packed.cine", frames, encoding="packed10")
    with Cine(output, canonical=True) as cine:
        assert cine.total_frames == 4
        assert np.array_equal(cine.image, first)
        assert cine.image_header.biCompression == 256
        offsets = cine.image_locations.pImage
        assert offsets.dtype == np.uint64
        assert len(offsets) == 5
        assert len(cine.image_locations.pImageData) == 32
        assert cine.annotation_size == 8
        assert len(cine.annotation_data) == 8
        assert len(cine.image_data) == cine.image_size


def test_writer_failure_does_not_publish(tmp_path):
    output = tmp_path / "incomplete.cine"
    with pytest.raises(ValueError):
        with CineWriter(output, width=4, height=2, dtype=np.uint8, frame_count=2) as writer:
            writer.write_frame(np.zeros((2, 4), dtype=np.uint8))
    assert not output.exists()
    with pytest.raises(RuntimeError):
        with CineWriter(output, width=4, height=2, dtype=np.uint8) as writer:
            writer.write_frame(np.zeros((2, 4), dtype=np.uint8))
            raise RuntimeError("stop")
    assert not output.exists()
    assert not list(tmp_path.iterdir())


def test_writer_rejects_existing_destination(tmp_path):
    output = tmp_path / "existing.cine"
    output.write_bytes(b"important")
    with pytest.raises(ValueError):
        write_cine(output, np.zeros((1, 2, 4), dtype=np.uint8))
    assert output.read_bytes() == b"important"


def test_trim_and_reopen_and_lazy_metadata(tmp_path):
    frames = np.arange(4 * 3 * 5, dtype=np.uint16).reshape(4, 3, 5)
    source = write_cine(tmp_path / "source.cine", frames, first_frame=-1)
    output = tmp_path / "trim.cine"
    with Cine(source, canonical=True) as cine:
        assert cine.camera_setup.Length > 0
        cine.save_frames_to_new_file(output, 0, 1)
        cine.open_cine_file(output)
        assert cine.total_frames == 2
        assert cine.first_frame_number == 0
        assert np.array_equal(cine.image, frames[1])
        assert isinstance(cine.camera_setup.SetupData, bytes)
        assert cine.file_handle.readable()
        cine.file_handle.seek(0)
        assert cine.file_handle.read(2) == b"CI"


def test_rgb_packed10_samples_bayer_and_scales_u8(tmp_path):
    frame = np.zeros((2, 4, 3), dtype=np.uint8)
    frame[..., 0], frame[..., 1], frame[..., 2] = 255, 128, 0
    output = write_cine(tmp_path / "bayer.cine", [frame], encoding="packed10")
    with Cine(output, canonical=True) as cine:
        assert cine.cfa_code == 4
        raw = cine.image
        assert raw.shape == (2, 4)
        assert raw[0, 0] >= 4090
        assert raw[1, 1] <= 2
        assert 2000 <= raw[0, 1] <= 2100
        assert np.isnan(cine.red_pixels[0, 1])
        assert cine.get_frame_rgb().shape == frame.shape


def test_image_files_and_video_stream(tmp_path):
    Image = pytest.importorskip("PIL.Image")
    frames = [np.full((4, 8, 3), value, dtype=np.uint8) for value in (32, 128, 224)]
    paths = []
    for index, frame in enumerate(frames):
        path = tmp_path / f"frame{index}.png"
        Image.fromarray(frame).save(path)
        paths.append(path)
    output = write_cine_from_images(tmp_path / "images.cine", paths)
    with Cine(output, canonical=True) as cine:
        cine.load_frame(2)
        assert np.array_equal(cine.image, frames[2])
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        pytest.skip("FFmpeg/FFprobe unavailable")
    video = tmp_path / "video.mkv"
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-framerate",
            "7",
            "-i",
            str(tmp_path / "frame%d.png"),
            "-c:v",
            "ffv1",
            str(video),
        ],
        check=True,
    )
    output = write_cine_from_video(tmp_path / "video.cine", video)
    with Cine(output, canonical=True) as cine:
        assert cine.total_frames == 3
        assert cine.frame_rate == pytest.approx(7)
        for index, expected in enumerate(frames):
            cine.load_frame(index)
            assert np.array_equal(cine.image, expected)


def test_lazy_frame_assignment_and_color_mutations(tmp_path):
    frame = np.arange(24, dtype=np.uint16).reshape(4, 6)
    path = write_cine(tmp_path / "lazy.cine", [frame], cfa=4)
    with Cine(path, canonical=True) as cine:
        replacement = np.full_like(frame, 77)
        cine.image = replacement
        assert not cine._pending_frame
        assert np.array_equal(cine.image, replacement)
        assert cine.red_pixels[0, 0] == 77
        cine.load_frame(0)
        cine.replace_dead_pixels(dead_value=0, dead_is_threshold=False)
        assert cine.red_pixels[0, 0] == cine.image[0, 0]
        raw_red = cine.red_pixels.copy()
        cine.debayer_frame()
        assert np.array_equal(cine.red_pixels, raw_red, equal_nan=True)
        cine.image = np.full((4, 6, 3), 31, dtype=np.uint16)
        assert np.all(cine.red_pixels == 31)
    with Cine(path) as cine:
        cine.pixel_array = replacement
        assert cine.pixel_array is replacement


def test_loaded_frame_payload_survives_close(tmp_path):
    path = write_cine(tmp_path / "closed.cine", [np.arange(8, dtype=np.uint16).reshape(2, 4)])
    cine = Cine(path)
    cine.load_frame(0)
    expected_size = cine.image_size
    cine.close_file()
    assert len(cine.image_data) == expected_size
    assert cine.pixel_array.shape == (2, 4)


@pytest.mark.parametrize("option", ["bit_depth", "cfa", "first_frame"])
def test_writer_rejects_fractional_integer_options(tmp_path, option):
    with pytest.raises(ValueError, match="must be an integer"):
        CineWriter(tmp_path / "fraction.cine", width=4, height=2, **{option: 1.5})
    assert not list(tmp_path.iterdir())


def test_explicit_close_preserves_initial_frame_and_lazy_metadata(tmp_path):
    frame = np.arange(8, dtype=np.uint16).reshape(2, 4)
    path = write_cine(tmp_path / "close-lazy.cine", [frame])
    cine = Cine(path, canonical=True)
    assert cine._pending_frame
    cine.close_file()
    assert np.array_equal(cine.image, frame)
    assert len(cine.image_locations.pImage) == 2
    assert len(cine.image_locations.pImageData) == 8
    assert len(cine.camera_setup.SetupData) >= cine.camera_setup.Length
    assert len(cine.image_data) == cine.image_size
