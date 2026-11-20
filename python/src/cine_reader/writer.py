"""Streaming Python conveniences around the shared Rust CINE encoder."""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from itertools import chain
from pathlib import Path
from typing import Iterable, Iterator

import numpy as np

from ._native import NativeWriter


class CineWriter:
    """Write frames incrementally, publishing a complete file on successful close.

    Arrays use top-down image coordinates and RGB channel order. ``normal``
    preserves uint8/uint16 values. ``packed10`` stores Phantom's nonlinear
    10-bit codes from linear 12-bit samples; uint8 is scaled to 0..4095.
    RGB packed10 input is sampled into a Bayer mosaic (CFA 4/RGGB by default).
    This is necessarily lossy; normal RGB is preferable for exact preservation.
    Existing destinations are never overwritten. A frame_count of None supports
    generators with bounded memory and a temporary disk spool.
    """

    def __init__(
        self,
        filename: str | Path,
        *,
        width: int,
        height: int,
        dtype=np.uint16,
        channels: int = 1,
        encoding: str = "normal",
        frame_count: int | None = None,
        frame_rate: float = 30.0,
        first_frame: int = 0,
        bit_depth: int | None = None,
        cfa: int = 0,
    ):
        for name, value in (("first_frame", first_frame), ("cfa", cfa), ("bit_depth", bit_depth)):
            if value is not None and int(value) != value:
                raise ValueError(f"{name} must be an integer")
        self.filename = str(filename)
        self.dtype = np.dtype(dtype)
        if self.dtype.kind != "u" or self.dtype.itemsize not in (1, 2):
            raise TypeError("dtype must be uint8 or uint16")
        if encoding not in ("normal", "packed10"):
            raise ValueError("encoding must be 'normal' or 'packed10'")
        if channels not in (1, 3):
            raise ValueError("channels must be 1 (mono/Bayer) or 3 (RGB)")
        if int(width) != width or int(height) != height or width <= 0 or height <= 0:
            raise ValueError("width and height must be positive integers")
        if frame_count is not None and (int(frame_count) != frame_count or frame_count <= 0):
            raise ValueError("frame_count must be a positive integer or None")
        self.width, self.height, self.channels = int(width), int(height), int(channels)
        self.encoding = encoding
        self.bit_depth = (
            (12 if encoding == "packed10" else self.dtype.itemsize * 8)
            if bit_depth is None
            else int(bit_depth)
        )
        if encoding == "normal" and ((self.bit_depth == 8) != (self.dtype.itemsize == 1)):
            raise ValueError("normal bit_depth=8 requires uint8; bit_depth=9..16 requires uint16")
        self.cfa = int(cfa)
        if encoding == "packed10" and channels == 3:
            self.cfa = self.cfa or 4
            if self.cfa not in (3, 4, 5, 6):
                raise ValueError("RGB packed10 encoding requires CFA 3, 4, 5 or 6")
        self._writer = NativeWriter(
            filename,
            width=self.width,
            height=self.height,
            channels=1 if encoding == "packed10" else channels,
            bit_depth=self.bit_depth,
            packed10=encoding == "packed10",
            frame_count=0 if frame_count is None else int(frame_count),
            first_frame=int(first_frame),
            frame_rate=float(frame_rate),
            cfa=self.cfa,
        )
        self.frames_written = 0
        self.closed = False

    def write_frame(self, frame: np.ndarray) -> None:
        """Append one frame. Shape and input dtype must match the constructor."""
        if self.closed:
            raise RuntimeError("CINE writer is closed")
        frame = np.asarray(frame)
        expected = (self.height, self.width) + ((3,) if self.channels == 3 else ())
        if frame.shape != expected:
            raise ValueError(f"frame shape {frame.shape} does not match {expected}")
        if frame.dtype.kind != "u" or frame.dtype.itemsize != self.dtype.itemsize:
            raise TypeError(f"frame dtype must match {self.dtype}")
        payload = np.ascontiguousarray(frame, dtype="<u2" if self.dtype.itemsize == 2 else np.uint8)
        self._writer.write_frame(payload)
        self.frames_written += 1

    def close(self) -> None:
        """Finalize the file; incomplete declared frame counts raise an error."""
        if not self.closed:
            try:
                self._writer.finish()
            finally:
                self.closed = True
                self._writer.close()

    def abort(self) -> None:
        """Discard an unfinished output and release temporary files."""
        if not self.closed:
            self.closed = True
            self._writer.close()

    def __enter__(self) -> "CineWriter":
        return self

    def __exit__(self, exc_type, exc, traceback) -> bool:
        if exc_type is None:
            self.close()
        else:
            self.abort()
        return False

    def __del__(self):
        if hasattr(self, "closed"):
            self.abort()


def write_cine(filename: str | Path, frames: Iterable[np.ndarray], **options) -> Path:
    """Encode a sequence or generator of identically shaped uint8/uint16 images.

    A NumPy stack is iterated on its first axis, ``[N,H,W]`` or ``[N,H,W,3]``.
    A sized sequence avoids the extra disk pass needed by unknown-length streams.
    The return value is the completed output path.
    """
    frame_count = options.pop("frame_count", None)
    if frame_count is None:
        try:
            frame_count = len(frames)
        except TypeError:
            pass
    iterator = iter(frames)
    try:
        first = np.asarray(next(iterator))
    except StopIteration as exc:
        raise ValueError("Cannot write an empty image sequence") from exc
    if first.ndim not in (2, 3) or (first.ndim == 3 and first.shape[2] != 3):
        raise ValueError("Each image must have shape [H,W] or [H,W,3]")
    with CineWriter(
        filename,
        width=first.shape[1],
        height=first.shape[0],
        dtype=first.dtype,
        channels=1 if first.ndim == 2 else 3,
        frame_count=frame_count,
        **options,
    ) as writer:
        for frame in chain((first,), iterator):
            writer.write_frame(frame)
    return Path(filename)


def write_cine_from_images(
    filename: str | Path, image_paths: Iterable[str | Path], **options
) -> Path:
    """Encode image files in their supplied order using optional Pillow.

    Paths are not sorted implicitly. RGB, grayscale and 16-bit grayscale are
    supported. Palette images become RGB; alpha channels are discarded.
    """
    try:
        from PIL import Image
    except ImportError as exc:
        raise ImportError(
            "Install image-file support with: pip install 'cine-handler[images]'"
        ) from exc
    if "frame_count" not in options:
        try:
            options["frame_count"] = len(image_paths)
        except TypeError:
            pass

    def images() -> Iterator[np.ndarray]:
        for path in image_paths:
            with Image.open(path) as image:
                if image.mode in ("P", "RGBA", "CMYK", "YCbCr"):
                    image = image.convert("RGB")
                elif image.mode in ("1", "LA"):
                    image = image.convert("L")
                pixels = np.asarray(image)
                if (
                    pixels.dtype.kind == "i"
                    and pixels.size
                    and pixels.min() >= 0
                    and pixels.max() <= 65535
                ):
                    pixels = pixels.astype(np.uint16)
                yield pixels

    return write_cine(filename, images(), **options)


def write_cine_from_video(
    filename: str | Path,
    video_filename: str | Path,
    *,
    encoding: str = "normal",
    grayscale: bool = False,
    frame_rate: float | None = None,
    ffmpeg: str = "ffmpeg",
    ffprobe: str = "ffprobe",
    backend: str | None = None,
    **options,
) -> Path:
    """Stream a video through optional PyAV into Rust, retaining one frame at a time.

    Install ``cine-handler[video]`` for video input without external executables.
    ``backend='ffmpeg'`` uses separately installed FFmpeg/FFprobe instead; supplying
    a custom ``ffmpeg`` or ``ffprobe`` path also selects that legacy backend unless
    ``backend`` is explicitly set. Decoding uses RGB8 or gray8;
    packed10 scales this to 12-bit and RGB becomes a Bayer mosaic. The first
    video stream is selected, stored pixel orientation is retained (rotation metadata
    is not applied), audio is ignored, and timestamps are represented
    by a constant rate (override frame_rate when converting variable-rate video).
    """
    if backend is None:
        backend = "ffmpeg" if ffmpeg != "ffmpeg" or ffprobe != "ffprobe" else "pyav"
    if backend not in ("pyav", "ffmpeg"):
        raise ValueError("backend must be 'pyav' or 'ffmpeg'")
    if frame_rate is not None:
        frame_rate = float(frame_rate)
        if not np.isfinite(frame_rate) or frame_rate <= 0:
            raise ValueError("frame_rate must be finite and positive")
    if backend == "pyav":
        return _write_cine_from_pyav(
            filename,
            video_filename,
            encoding=encoding,
            grayscale=grayscale,
            frame_rate=frame_rate,
            **options,
        )
    return _write_cine_from_ffmpeg(
        filename,
        video_filename,
        encoding=encoding,
        grayscale=grayscale,
        frame_rate=frame_rate,
        ffmpeg=ffmpeg,
        ffprobe=ffprobe,
        **options,
    )


def _write_cine_from_pyav(
    filename: str | Path,
    video_filename: str | Path,
    *,
    encoding: str,
    grayscale: bool,
    frame_rate: float | None,
    **options,
) -> Path:
    try:
        import av
    except ImportError as exc:
        raise ImportError("Install video support with: pip install 'cine-handler[video]'") from exc

    with av.open(str(video_filename), mode="r") as container:
        if not container.streams.video:
            raise ValueError("Input contains no video stream")
        stream = container.streams.video[0]
        if frame_rate is None:
            for candidate in (stream.average_rate, stream.base_rate, stream.guessed_rate):
                if candidate is not None:
                    rate = float(candidate)
                    if np.isfinite(rate) and rate > 0:
                        frame_rate = rate
                        break
            if frame_rate is None:
                raise ValueError("Video frame rate is unknown; specify frame_rate")
        width, height = stream.codec_context.width, stream.codec_context.height
        if width <= 0 or height <= 0:
            raise ValueError("Video width and height must be positive")
        with CineWriter(
            filename,
            width=width,
            height=height,
            channels=1 if grayscale else 3,
            dtype=np.uint8,
            encoding=encoding,
            frame_rate=frame_rate,
            **options,
        ) as writer:
            for frame in container.decode(stream):
                if frame.width != width or frame.height != height:
                    raise ValueError("Video frame dimensions changed during decoding")
                writer.write_frame(frame.to_ndarray(format="gray" if grayscale else "rgb24"))
            if writer.frames_written == 0:
                raise ValueError("Video contains no decoded frames")
    return Path(filename)


def _write_cine_from_ffmpeg(
    filename: str | Path,
    video_filename: str | Path,
    *,
    encoding: str,
    grayscale: bool,
    frame_rate: float | None,
    ffmpeg: str,
    ffprobe: str,
    **options,
) -> Path:
    for executable in (ffmpeg, ffprobe):
        if not shutil.which(executable):
            raise FileNotFoundError(f"Required video tool was not found: {executable}")
    metadata = subprocess.run(
        [
            ffprobe,
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=width,height,avg_frame_rate,r_frame_rate",
            "-of",
            "json",
            str(video_filename),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    streams = json.loads(metadata.stdout).get("streams", [])
    if not streams:
        raise ValueError("Input contains no video stream")
    stream = streams[0]
    if frame_rate is None:
        for key in ("avg_frame_rate", "r_frame_rate"):
            try:
                numerator, denominator = (float(part) for part in stream.get(key, "0/0").split("/"))
                rate = numerator / denominator
            except (ValueError, ZeroDivisionError):
                continue
            if np.isfinite(rate) and rate > 0:
                frame_rate = rate
                break
        if frame_rate is None:
            raise ValueError("Video frame rate is unknown; specify frame_rate")
    width, height = int(stream["width"]), int(stream["height"])
    channels = 1 if grayscale else 3
    shape = (height, width) + (() if grayscale else (3,))
    frame_bytes = width * height * channels
    command = [
        ffmpeg,
        "-v",
        "error",
        "-noautorotate",
        "-i",
        str(video_filename),
        "-map",
        "0:v:0",
        "-an",
        "-sn",
        "-dn",
        "-fps_mode",
        "passthrough",
        "-f",
        "rawvideo",
        "-pix_fmt",
        "gray" if grayscale else "rgb24",
        "pipe:1",
    ]
    with tempfile.TemporaryFile() as errors:
        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=errors)
        assert process.stdout is not None
        try:
            with CineWriter(
                filename,
                width=width,
                height=height,
                channels=channels,
                dtype=np.uint8,
                encoding=encoding,
                frame_rate=frame_rate,
                **options,
            ) as writer:
                while True:
                    payload = bytearray(frame_bytes)
                    view = memoryview(payload)
                    position = 0
                    while position < frame_bytes:
                        size = process.stdout.readinto(view[position:])
                        if not size:
                            break
                        position += size
                    if position == 0:
                        break
                    if position != frame_bytes:
                        raise ValueError("FFmpeg returned a truncated frame")
                    writer.write_frame(np.frombuffer(payload, dtype=np.uint8).reshape(shape))
                status = process.wait()
                if status:
                    errors.seek(0)
                    raise RuntimeError(
                        f"FFmpeg decoding failed: {errors.read().decode(errors='replace')}"
                    )
                if writer.frames_written == 0:
                    raise ValueError("Video contains no decoded frames")
        finally:
            process.stdout.close()
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
    return Path(filename)
