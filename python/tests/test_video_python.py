"""Video input works using Python packages alone, with bounded frame decoding."""

from __future__ import annotations

import sys
import wave
from fractions import Fraction

import numpy as np
import pytest

from cine_reader import Cine, write_cine_from_video
from cine_reader import writer as writer_module

av = pytest.importorskip("av")


def make_video(path, frames, rate=Fraction(30000, 1001)):
    with av.open(str(path), "w") as container:
        stream = container.add_stream("ffv1", rate=rate)
        stream.width = frames[0].shape[1]
        stream.height = frames[0].shape[0]
        stream.pix_fmt = "bgr0"
        for pixels in frames:
            frame = av.VideoFrame.from_ndarray(pixels, format="rgb24")
            for packet in stream.encode(frame):
                container.mux(packet)
        for packet in stream.encode():
            container.mux(packet)
    return path


@pytest.mark.parametrize("grayscale", [False, True])
@pytest.mark.parametrize("rate_override", [None, 12.5])
def test_video_roundtrip_without_executables(tmp_path, monkeypatch, grayscale, rate_override):
    mono = np.arange(48, dtype=np.uint8).reshape(6, 8)
    if grayscale:
        frames = [np.repeat((mono + offset)[..., None], 3, axis=2) for offset in (0, 73, 150)]
    else:
        rgb = np.arange(144, dtype=np.uint8).reshape(6, 8, 3)
        frames = [rgb, np.flip(rgb, axis=0).copy(), np.flip(rgb, axis=2).copy()]
    video = make_video(tmp_path / "source.mkv", frames)
    monkeypatch.setenv("PATH", "")
    output = write_cine_from_video(
        tmp_path / "video.cine", video, grayscale=grayscale, frame_rate=rate_override
    )
    with Cine(output, canonical=True) as cine:
        assert cine.total_frames == len(frames)
        assert cine.frame_rate == pytest.approx(rate_override or float(Fraction(30000, 1001)))
        for index, expected in enumerate(frames):
            cine.load_frame(index)
            assert cine.image.dtype == np.uint8
            assert np.array_equal(cine.image, expected[..., 0] if grayscale else expected)


def test_missing_video_package_has_install_hint(tmp_path, monkeypatch):
    monkeypatch.setitem(sys.modules, "av", None)
    with pytest.raises(ImportError, match=r"cine-handler\[video\]"):
        write_cine_from_video(tmp_path / "output.cine", tmp_path / "input.mp4")
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize("rate", [0, -1, float("nan"), float("inf")])
def test_invalid_video_rate_does_not_create_output(tmp_path, rate):
    with pytest.raises(ValueError, match="frame_rate must be finite and positive"):
        write_cine_from_video(tmp_path / "output.cine", tmp_path / "input.mp4", frame_rate=rate)
    assert not list(tmp_path.iterdir())


def test_audio_only_input_is_rejected(tmp_path, monkeypatch):
    audio = tmp_path / "audio.wav"
    with wave.open(str(audio), "wb") as recording:
        recording.setnchannels(1)
        recording.setsampwidth(2)
        recording.setframerate(8000)
        recording.writeframes(bytes(1600))
    monkeypatch.setenv("PATH", "")
    output = tmp_path / "output.cine"
    with pytest.raises(ValueError, match="no video stream"):
        write_cine_from_video(output, audio)
    assert not output.exists()


def test_invalid_video_is_rejected_without_output(tmp_path, monkeypatch):
    video = tmp_path / "invalid.mp4"
    video.write_bytes(b"This is not a video file.")
    monkeypatch.setenv("PATH", "")
    output = tmp_path / "output.cine"
    with pytest.raises(av.error.InvalidDataError):
        write_cine_from_video(output, video)
    assert not output.exists()


@pytest.mark.parametrize("failure", ["empty", "decoder", "dimensions"])
def test_partial_video_failure_aborts_output_and_closes_input(tmp_path, monkeypatch, failure):
    frames = [np.full((6, 8, 3), value, dtype=np.uint8) for value in (32, 128, 224)]
    video = make_video(tmp_path / "source.mkv", frames)
    recording = av.open(str(video))
    output_directory = tmp_path / "output"
    output_directory.mkdir()
    written = []

    class ObservedWriter(writer_module.CineWriter):
        def write_frame(self, frame):
            super().write_frame(frame)
            written.append(self.frames_written)

    monkeypatch.setattr(writer_module, "CineWriter", ObservedWriter)

    class InterruptedInput:
        streams = recording.streams
        closed = False

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            recording.close()
            self.closed = True

        def decode(self, stream):
            if failure == "empty":
                return
            yield next(recording.decode(stream))
            # The first frame must reach Rust before requesting another decoded
            # frame; materializing the decoder into a list violates streaming.
            assert written == [1]
            if failure == "decoder":
                raise RuntimeError("Decoder failed after a complete frame")
            yield av.VideoFrame.from_ndarray(np.zeros((4, 8, 3), dtype=np.uint8), format="rgb24")

    interrupted = InterruptedInput()
    monkeypatch.setattr(av, "open", lambda *args, **kwargs: interrupted)
    monkeypatch.setenv("PATH", "")
    with pytest.raises((RuntimeError, ValueError)):
        write_cine_from_video(output_directory / "output.cine", video)
    assert interrupted.closed
    assert not list(output_directory.iterdir())


def test_explicit_executable_override_keeps_legacy_backend(tmp_path):
    with pytest.raises(FileNotFoundError, match="Required video tool was not found"):
        write_cine_from_video(
            tmp_path / "output.cine",
            tmp_path / "input.mp4",
            ffmpeg=str(tmp_path / "custom-ffmpeg-does-not-exist"),
        )
    assert not list(tmp_path.iterdir())
