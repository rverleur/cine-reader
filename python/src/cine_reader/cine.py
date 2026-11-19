"""High-level Phantom CINE reader with pythonic APIs and documented aliases."""

from __future__ import annotations

import io
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import BinaryIO, Iterator

import numpy as np

from ._native import NativeReader
from .frame_decode import decode_frame_payload
from .headers import (
    BitmapHeader,
    CineHeader,
    ImageOffsets,
    Setup,
    read_bitmap_header,
    read_cine_header,
    read_setup,
)
from .image_ops import demosaic_bilinear
from .image_ops import replace_dead_pixels as repair_dead_pixels
from .stats import average_from_frame_iter, robust_background_mad_stack, robust_background_topk
from .unpack import unpack_10bit_data


class Cine:
    """High-level reader for Vision Research Phantom `.cine` files.

    Notes
    -----
    Metadata field names inside `file_header`, `image_header`, and `camera_setup`
    follow the CINE specification naming (CamelCase / `bi*` fields). Python-facing
    methods and top-level aliases use snake_case.
    """

    def __init__(
        self,
        filename: str | Path,
        keep_annotations: bool = True,
        *,
        remove_dead_pixels: bool = False,
        debayer: bool = False,
        dead_value: int | None = None,
        dead_is_threshold: bool = True,
        bayer_pattern: str = "auto",
        canonical: bool = False,
    ):
        """Create and open a CINE file reader.

        Parameters
        ----------
        filename:
            Path to the `.cine` file.
        keep_annotations:
            If `True`, keep per-frame annotation payload bytes available in
            `annotation_data` and `annotation`.
        remove_dead_pixels:
            If `True`, dead-pixel repair is applied every time a frame is loaded.
        debayer:
            If `True`, raw color CFA/Bayer frames are debayered every time a
            frame is loaded.
        dead_value:
            Optional dead-pixel marker/threshold used when `remove_dead_pixels`
            is enabled. If `None`, it is inferred from setup metadata.
        dead_is_threshold:
            If `True`, values `>= dead_value` are repaired.
        bayer_pattern:
            Bayer layout token for debayering. Use `"auto"` to infer from setup
            `CFA`.
        """
        self._pending_frame = False
        self._color_samples_pending = None
        self._image_data_pending = False
        self.canonical = bool(canonical)
        self.filename = str(filename)
        self.keep_annotations = bool(keep_annotations)
        self.remove_dead_pixels = bool(remove_dead_pixels)
        self.debayer = bool(debayer)
        self.dead_value = dead_value
        self.dead_is_threshold = bool(dead_is_threshold)
        self.bayer_pattern_mode = str(bayer_pattern)

        self.file_handle: BinaryIO | None = None
        self.file_header: CineHeader | None = None
        self.image_header: BitmapHeader | None = None
        self.camera_setup: Setup | None = None
        self.image_locations: ImageOffsets | None = None

        self.current_frame: int | None = None
        self.pixel_array: np.ndarray | None = None
        self.pixel_data: np.ndarray | None = None
        self.red_pixels: np.ndarray | None = None
        self.green_pixels: np.ndarray | None = None
        self.blue_pixels: np.ndarray | None = None
        self.annotation_size: int = 0
        self.annotation_data: bytes = b""
        self.annotation: bytes = b""
        self.image_size: int = 0
        self.image_data: bytes = b""
        self._pixel_array_channel_order: str | None = None
        self._color_samples_from_raw_cfa = False

        self._recording_datetime: datetime | None = None

        self.open_cine_file(self.filename)

    def __enter__(self) -> "Cine":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        self.close_file()
        return False

    def __del__(self) -> None:
        try:
            self._release_reader()
        except Exception:
            pass

    @property
    def first_frame_number(self) -> int:
        """Alias for `file_header.FirstImageNo`."""
        header = self._require_file_header()
        return int(header.FirstImageNo)

    @property
    def total_frames(self) -> int:
        """Alias for `file_header.ImageCount`."""
        header = self._require_file_header()
        return int(header.ImageCount)

    @property
    def last_frame_number(self) -> int:
        """Derived final frame number (`FirstImageNo + ImageCount - 1`)."""
        return self.first_frame_number + self.total_frames - 1

    @property
    def frame_rate(self) -> float:
        """Best available frame rate in Hz (prefers floating-point setup value)."""
        setup = self._require_camera_setup()
        return setup.frame_rate_hz

    @property
    def exposure_time_ns(self) -> int:
        """Best available exposure time in nanoseconds."""
        setup = self._require_camera_setup()
        return setup.exposure_time_ns

    @property
    def exposure_time_seconds(self) -> float:
        """Best available exposure time in seconds."""
        setup = self._require_camera_setup()
        return setup.exposure_time_seconds

    @property
    def exposure_time(self) -> float:
        """Alias for `exposure_time_seconds`."""
        return self.exposure_time_seconds

    @property
    def recording_datetime(self) -> datetime | None:
        """Recording timestamp derived from `TriggerTime` and setup timezone."""
        return self._recording_datetime

    @property
    def recording_date(self) -> date | None:
        """Recording calendar date derived from `recording_datetime`."""
        dt = self._recording_datetime
        return dt.date() if dt is not None else None

    @property
    def cfa_code(self) -> int:
        """Color Filter Array code from setup metadata."""
        setup = self._require_camera_setup()
        return int(getattr(setup, "CFA", 0))

    @property
    def bayer_pattern(self) -> str | None:
        """Best-effort Bayer pattern inferred from `camera_setup.CFA`."""
        return self._resolve_bayer_pattern()

    @property
    def image(self) -> np.ndarray:
        """Alias for latest decoded frame array (`pixel_array`)."""
        arr = self.pixel_array
        if arr is None:
            raise RuntimeError("No frame loaded.")
        return arr

    @image.setter
    def image(self, value: np.ndarray) -> None:
        self._pending_frame = False
        self.pixel_array = np.asarray(value)
        self.pixel_data = self.pixel_array.reshape(-1)
        self._pixel_array_channel_order = "RGB" if self.pixel_array.ndim == 3 else None
        self._update_color_sample_arrays(self.pixel_array)

    @property
    def frame(self) -> np.ndarray:
        """Alias for latest decoded frame array (`pixel_array`)."""
        return self.image

    @frame.setter
    def frame(self, value: np.ndarray) -> None:
        self.image = value

    _FRAME_ATTRIBUTES = frozenset(
        {
            "pixel_array",
            "pixel_data",
            "red_pixels",
            "green_pixels",
            "blue_pixels",
            "annotation_size",
            "annotation_data",
            "annotation",
            "image_size",
            "image_data",
        }
    )

    def __setattr__(self, name, value):
        # Direct pixel_array assignment is part of the existing public surface.
        # It must not be overwritten by a still-pending implicit initial load.
        if name == "pixel_array" and self.__dict__.get("_pending_frame", False):
            self.__dict__["_pending_frame"] = False
        object.__setattr__(self, name, value)

    def __getattribute__(self, name):
        if name in Cine._FRAME_ATTRIBUTES:
            state = object.__getattribute__(self, "__dict__")
            if state.get("_pending_frame", False):
                object.__getattribute__(self, "load_frame")(state["current_frame"])
            if name in {"red_pixels", "green_pixels", "blue_pixels"}:
                pending = state.get("_color_samples_pending")
                if pending is not None:
                    state["_color_samples_pending"] = None
                    object.__getattribute__(self, "_update_color_sample_arrays")(pending)
            if name == "image_data" and state.get("_image_data_pending", False):
                state["image_data"] = object.__getattribute__(self, "_require_file_handle")().block(
                    4
                )
                state["_image_data_pending"] = False
        return object.__getattribute__(self, name)

    def open_cine_file(self, filename: str | Path) -> None:
        """Open metadata immediately; decode the initial frame on first access.

        Offset tables, tagged setup bytes and channel sample arrays are also
        materialized only when their existing public attributes are accessed.
        """
        self._release_reader()
        self.filename = str(filename)
        reader = NativeReader(filename)
        self.file_handle = reader
        try:
            self.file_header = read_cine_header(io.BytesIO(reader.block(0)))
            self.image_header = read_bitmap_header(io.BytesIO(reader.block(1)), off_image_header=0)
            setup = reader.block(2)
            self.camera_setup = read_setup(
                io.BytesIO(setup), off_setup=0, off_image_offsets=len(setup)
            )
            self.camera_setup._setup_data_loader = lambda: reader.block(5)
            self.image_locations = ImageOffsets(pImageData=b"", pImage=np.empty(0, dtype=np.uint64))
            version = self.file_header.Version

            def load_offsets():
                raw = reader.block(6)
                offsets = np.frombuffer(raw, dtype="<u8" if version == 1 else "<u4").astype(
                    np.uint64, copy=False
                )
                return raw, np.append(offsets, np.uint64(reader.info.file_size))

            self.image_locations._lazy_loader = load_offsets
            self._recording_datetime = self._decode_recording_datetime(
                trigger_time=int(self.file_header.TriggerTime),
                recording_tz_seconds=int(self.camera_setup.RecordingTimeZone),
            )
            self.current_frame = int(self.file_header.FirstImageNo)
            self._color_samples_pending = None
            self._image_data_pending = False
            self.pixel_array = self.pixel_data = None
            self.red_pixels = self.green_pixels = self.blue_pixels = None
            self.annotation_size = self.image_size = 0
            self.annotation = self.annotation_data = self.image_data = b""
            self._pending_frame = self.total_frames > 0
        except Exception:
            self._release_reader()
            raise

    def close_file(self) -> None:
        """Close while retaining the legacy public frame and metadata state.

        Deferred data is materialized here so it remains accessible after close.
        Object destruction and reopening release resources without doing this.
        """
        reader = getattr(self, "file_handle", None)
        if reader is None or reader.closed:
            return
        try:
            if self.__dict__.get("_pending_frame", False):
                self.load_frame(self.current_frame)
            if self.__dict__.get("_image_data_pending", False):
                self.image_data = reader.block(4)
            setup = getattr(self, "camera_setup", None)
            if setup is not None:
                _ = setup.SetupData
            locations = getattr(self, "image_locations", None)
            if locations is not None:
                _ = locations.pImage
        finally:
            self._release_reader()

    def _release_reader(self) -> None:
        """Release native resources without reading deferred public state."""
        reader = getattr(self, "file_handle", None)
        if reader is not None and not reader.closed:
            reader.close()
        self.file_handle = None
        self._pending_frame = False
        self._image_data_pending = False

    def next_frame(self, increment: int = 1, *, convert_bgr_to_rgb: bool = False) -> None:
        """Load the next frame relative to `current_frame`.

        Parameters
        ----------
        increment:
            Number of frame numbers to advance (negative values are allowed).
        convert_bgr_to_rgb:
            If `True` and data is 3-channel, convert BGR payload order to RGB.
        """
        if self.current_frame is None:
            raise RuntimeError("No current frame is set.")
        self.load_frame(self.current_frame + int(increment), convert_bgr_to_rgb=convert_bgr_to_rgb)

    def load_frame(self, image_no: int, *, convert_bgr_to_rgb: bool = False) -> None:
        """Load one frame into `pixel_array`.

        Parameters
        ----------
        image_no:
            Global frame number (`FirstImageNo .. last_frame_number`) as defined
            by the CINE header table.
        convert_bgr_to_rgb:
            If `True`, convert 3-channel frame data from BGR to RGB.
        """
        reader = self._require_file_handle()
        index = int(image_no) - self.first_frame_number
        flags = 3 if self.canonical else 0
        if convert_bgr_to_rgb:
            flags |= 2
        frame, details, annotation = reader.load(
            index, flags=flags, annotations=self.keep_annotations
        )
        self._pending_frame = False
        self.current_frame = int(image_no)
        self.annotation_size = details.annotation_size
        self.image_size = details.image_size
        self.annotation_data = annotation
        self.annotation = annotation[4:-4] if annotation else b""
        self.image_data = b""
        self._image_data_pending = True
        if self.remove_dead_pixels:
            frame = self._repair_dead_pixels_array(frame)
        self._pixel_array_channel_order = (
            "RGB" if frame.ndim == 3 and flags & 2 else self._decoded_channel_order(frame)
        )
        self._color_samples_from_raw_cfa = self._is_raw_bayer_frame(frame)
        self.red_pixels = self.green_pixels = self.blue_pixels = None
        self._color_samples_pending = frame
        if self.debayer and self._is_raw_bayer_frame(frame):
            frame = self._debayer_array(frame, bayer_pattern=self.bayer_pattern_mode)
            self._pixel_array_channel_order = "RGB"
        self.pixel_array = frame
        self.pixel_data = frame.reshape(-1)

    def replace_dead_pixels(
        self,
        dead_value: int | None = None,
        *,
        dead_is_threshold: bool = True,
    ) -> None:
        """Replace dead pixels in mono, Bayer raw, or RGB frames.

        Parameters
        ----------
        dead_value:
            Dead-pixel marker value or threshold. If `None`, inferred from
            setup metadata (`WhiteLevel + 1` when available, else sensor max).
        dead_is_threshold:
            If `True`, repair pixels where value is `>= dead_value`.
            If `False`, repair pixels where value equals `dead_value`.
        """
        frame = self._require_pixel_array()
        self.pixel_array = self._repair_dead_pixels_array(
            frame,
            dead_value=dead_value,
            dead_is_threshold=dead_is_threshold,
        )
        if not (self.pixel_array.ndim == 3 and self._color_samples_from_raw_cfa):
            self._update_color_sample_arrays(self.pixel_array)
        self.pixel_data = self.pixel_array.reshape(-1)

    def debayer_frame(self, *, bayer_pattern: str = "auto") -> None:
        """Debayer the currently loaded raw CFA/Bayer frame in-place.

        This mutates `pixel_array` to an RGB `[H, W, 3]` image. Raw CFA sample
        arrays (`red_pixels`, `green_pixels`, `blue_pixels`) remain based on the
        pre-debayer sensor mosaic.
        """
        frame = self._require_pixel_array()
        if frame.ndim == 3:
            if self._pixel_array_channel_order == "BGR":
                self.pixel_array = frame[..., ::-1].copy()
                self._pixel_array_channel_order = "RGB"
                self._update_color_sample_arrays(self.pixel_array)
                self.pixel_data = self.pixel_array.reshape(-1)
            return
        if not self._is_raw_bayer_frame(frame):
            raise ValueError("Current frame is not a raw color CFA/Bayer frame.")

        self._update_color_sample_arrays(frame)
        self.pixel_array = self._debayer_array(frame, bayer_pattern=bayer_pattern)
        self._pixel_array_channel_order = "RGB"
        self.pixel_data = self.pixel_array.reshape(-1)

    def save_frames_to_new_file(
        self, output_filename: str | Path, start_frame: int, end_frame: int
    ) -> None:
        """Write a trimmed CINE file for frame range `[start_frame, end_frame]`.

        Parameters
        ----------
        output_filename:
            Output path for the new CINE file.
        start_frame:
            First global frame number to include.
        end_frame:
            Last global frame number to include (inclusive).
        """
        reader = self._require_file_handle()
        first, _ = self._validate_frame_range(start_frame, end_frame)
        reader.trim(output_filename, start_frame - first, end_frame - start_frame + 1)

    def average_frames(
        self,
        start_frame: int,
        end_frame: int,
        *,
        replace_dead_pixels: bool = False,
        chunk_size: int = 8,
    ) -> np.ndarray:
        """Compute per-pixel mean over an inclusive frame range.

        Parameters
        ----------
        start_frame:
            First global frame number to include.
        end_frame:
            Last global frame number to include (inclusive).
        replace_dead_pixels:
            If `True`, run dead-pixel replacement per frame before averaging.
        chunk_size:
            Number of frames accumulated per chunk for lower Python overhead.

        Returns
        -------
        numpy.ndarray
            Averaged frame with dtype matching the currently loaded frame.
        """
        self._validate_frame_range(start_frame, end_frame)
        current = self._require_pixel_array()
        frame_iter = self._iter_loaded_frames(
            start_frame,
            end_frame,
            replace_dead_pixels=replace_dead_pixels,
        )
        avg, _ = average_from_frame_iter(frame_iter, out_dtype=current.dtype, chunk_size=chunk_size)
        return avg

    def mode_frames(
        self,
        start_frame: int,
        end_frame: int,
        *,
        replace_dead_pixels: bool = False,
        method: str = "auto",
        q_bg: float = 0.80,
        k_sigma: float = 2.5,
        min_keep: int = 3,
        max_keep: int | None = 96,
        stack_limit: int = 128,
    ) -> np.ndarray:
        """Estimate robust bright background over a frame range.

        Parameters
        ----------
        start_frame:
            First global frame number to include.
        end_frame:
            Last global frame number to include (inclusive).
        replace_dead_pixels:
            If `True`, run dead-pixel replacement per frame before processing.
        method:
            `"auto"`, `"mad"`, or `"topk"` background estimator.
        q_bg:
            Bright-background quantile threshold (0..1).
        k_sigma:
            MAD rejection multiplier used by `method="mad"`.
        min_keep:
            Minimum accepted samples per pixel.
        max_keep:
            Upper cap for top-k memory (used by `method="topk"`).
        stack_limit:
            For `method="auto"`, frame-count threshold for switching from
            full-stack MAD to top-k.

        Returns
        -------
        numpy.ndarray
            Robust background image (`uint16`).
        """
        self._validate_frame_range(start_frame, end_frame)
        frame_count = end_frame - start_frame + 1
        method_norm = method.lower().strip()
        if method_norm == "auto":
            method_norm = "mad" if frame_count <= stack_limit else "topk"

        frame_iter = self._iter_loaded_frames(
            start_frame,
            end_frame,
            replace_dead_pixels=replace_dead_pixels,
        )
        if method_norm == "mad":
            return robust_background_mad_stack(
                frame_iter,
                q_bg=q_bg,
                k_sigma=k_sigma,
                min_keep=min_keep,
                out_dtype=np.uint16,
            )
        if method_norm == "topk":
            return robust_background_topk(
                frame_iter,
                frame_count=frame_count,
                q_bg=q_bg,
                min_keep=min_keep,
                max_keep=max_keep,
                out_dtype=np.uint16,
            )
        raise ValueError("method must be one of: 'auto', 'mad', 'topk'")

    def load_frames_batch(self, start_frame: int, count: int) -> np.ndarray:
        """Load `count` consecutive frames into one stacked array.

        Parameters
        ----------
        start_frame:
            First global frame number to include.
        count:
            Number of consecutive frames to load.

        Returns
        -------
        numpy.ndarray
            Stacked array with frame dimension on the last axis.
            Mono/raw CFA: `[H, W, N]`; debayered/interpolated color:
            `[H, W, 3, N]`.
        """
        if count <= 0:
            raise ValueError("count must be > 0")
        stop_frame = start_frame + count - 1
        self._validate_frame_range(start_frame, stop_frame)

        self.load_frame(start_frame)
        first = self._require_pixel_array().copy()
        out = np.empty(first.shape + (count,), dtype=first.dtype)
        out[..., 0] = first

        for idx, frame_no in enumerate(range(start_frame + 1, stop_frame + 1), start=1):
            self.load_frame(frame_no)
            out[..., idx] = self._require_pixel_array()
        return out

    def get_frame_rgb(
        self, image_no: int | None = None, *, bayer_pattern: str = "auto"
    ) -> np.ndarray:
        """Return current or selected frame as RGB.

        Parameters
        ----------
        image_no:
            Optional global frame number to load before conversion.
        bayer_pattern:
            Bayer layout token for mono demosaic (`RGGB`, `BGGR`, `GRBG`, `GBRG`).
            Use `"auto"` to infer from setup `CFA`.

        Returns
        -------
        numpy.ndarray
            RGB frame.
        """
        if image_no is not None:
            self.load_frame(image_no)

        frame = self._require_pixel_array()
        if frame.ndim == 3:
            if self._pixel_array_channel_order == "BGR":
                return frame[..., ::-1].copy()
            return frame.copy()
        if frame.ndim == 2:
            pattern = self._resolve_bayer_pattern(bayer_pattern) or "RGGB"
            return demosaic_bilinear(frame, pattern=pattern)
        raise ValueError("Unsupported frame shape for RGB conversion")

    def _decode_frame(self, raw: bytes) -> np.ndarray:
        image_header = self._require_image_header()
        setup = self._require_camera_setup()
        return decode_frame_payload(
            raw,
            bit_count=int(image_header.biBitCount),
            width=int(image_header.biWidth),
            height_signed=int(image_header.biHeight),
            real_bpp=int(setup.RealBPP),
            unpack_10bit_fn=unpack_10bit_data,
            compression=int(image_header.biCompression),
        )

    def _repair_dead_pixels_array(
        self,
        frame: np.ndarray,
        *,
        dead_value: int | None = None,
        dead_is_threshold: bool | None = None,
    ) -> np.ndarray:
        resolved_dead = self._resolve_dead_value(
            self.dead_value if dead_value is None else dead_value
        )
        resolved_threshold = (
            self.dead_is_threshold if dead_is_threshold is None else bool(dead_is_threshold)
        )
        return repair_dead_pixels(
            frame,
            dead_value=resolved_dead,
            dead_is_threshold=resolved_threshold,
            bayer_raw=self._is_raw_bayer_frame(frame),
        )

    def _debayer_array(self, frame: np.ndarray, *, bayer_pattern: str = "auto") -> np.ndarray:
        pattern = self._resolve_bayer_pattern(bayer_pattern) or "RGGB"
        return demosaic_bilinear(frame, pattern=pattern)

    def _update_color_sample_arrays(self, frame: np.ndarray) -> None:
        self._color_samples_pending = None
        self._color_samples_from_raw_cfa = False

        if self._is_raw_bayer_frame(frame):
            pattern = self._resolve_bayer_pattern(self.bayer_pattern_mode) or "RGGB"
            red, green, blue = self._raw_cfa_sample_arrays(frame.shape)
            for row_phase, col_phase, channel in self._bayer_color_phases(pattern):
                rows = slice(row_phase, None, 2)
                cols = slice(col_phase, None, 2)
                if channel == "R":
                    red[rows, cols] = frame[rows, cols]
                elif channel == "G":
                    green[rows, cols] = frame[rows, cols]
                else:
                    blue[rows, cols] = frame[rows, cols]
            self.red_pixels = red
            self.green_pixels = green
            self.blue_pixels = blue
            self._color_samples_from_raw_cfa = True
            return

        self.red_pixels = None
        self.green_pixels = None
        self.blue_pixels = None

        if frame.ndim == 3 and frame.shape[-1] >= 3:
            image_header = self._require_image_header()
            channels = frame
            if (
                int(image_header.biBitCount) in (24, 48)
                and self._pixel_array_channel_order != "RGB"
            ):
                channels = frame[..., ::-1]
            self.red_pixels = channels[..., 0].astype(np.float32, copy=True)
            self.green_pixels = channels[..., 1].astype(np.float32, copy=True)
            self.blue_pixels = channels[..., 2].astype(np.float32, copy=True)

    def _raw_cfa_sample_arrays(
        self, shape: tuple[int, int]
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        arrays = []
        for current in (self.red_pixels, self.green_pixels, self.blue_pixels):
            if current is not None and current.shape == shape and current.dtype == np.float32:
                sample = current
                sample.fill(np.nan)
            else:
                sample = np.full(shape, np.nan, dtype=np.float32)
            arrays.append(sample)
        return arrays[0], arrays[1], arrays[2]

    @staticmethod
    def _bayer_color_phases(pattern: str) -> tuple[tuple[int, int, str], ...]:
        token = pattern.upper()
        mapping = {
            "RGGB": ((0, 0, "R"), (0, 1, "G"), (1, 0, "G"), (1, 1, "B")),
            "BGGR": ((0, 0, "B"), (0, 1, "G"), (1, 0, "G"), (1, 1, "R")),
            "GRBG": ((0, 0, "G"), (0, 1, "R"), (1, 0, "B"), (1, 1, "G")),
            "GBRG": ((0, 0, "G"), (0, 1, "B"), (1, 0, "R"), (1, 1, "G")),
        }
        try:
            return mapping[token]
        except KeyError as exc:
            raise ValueError(f"Unsupported Bayer pattern: {pattern}") from exc

    def _decoded_channel_order(self, frame: np.ndarray) -> str | None:
        if frame.ndim != 3:
            return None
        image_header = self._require_image_header()
        if int(image_header.biBitCount) in (24, 48):
            return "BGR"
        return "RGB"

    def _validate_frame_range(self, start_frame: int, end_frame: int) -> tuple[int, int]:
        header = self._require_file_header()
        first = int(header.FirstImageNo)
        last = first + int(header.ImageCount) - 1
        if start_frame < first or end_frame > last or end_frame < start_frame:
            raise ValueError("Frame range out of bounds.")
        return first, last

    def _iter_loaded_frames(
        self,
        start_frame: int,
        end_frame: int,
        *,
        replace_dead_pixels: bool = False,
    ) -> Iterator[np.ndarray]:
        """Yield decoded frame arrays over `[start_frame, end_frame]`."""
        load_frame = self.load_frame
        replace = self.replace_dead_pixels
        for frame_no in range(start_frame, end_frame + 1):
            load_frame(frame_no)
            if replace_dead_pixels and not self.remove_dead_pixels:
                replace()
            yield self._require_pixel_array()

    def _is_raw_bayer_frame(self, frame: np.ndarray) -> bool:
        """Return True when frame is 2D and setup indicates uninterpolated color."""
        if frame.ndim != 2:
            return False
        image_header = self._require_image_header()
        if int(image_header.biBitCount) not in (8, 16):
            return False
        setup = self._require_camera_setup()
        return bool(getattr(setup, "bEnableColor", False)) and self.cfa_code != 0

    def _resolve_bayer_pattern(self, bayer_pattern: str = "auto") -> str | None:
        """Resolve Bayer pattern from explicit token or setup CFA code."""
        token = bayer_pattern.upper().strip()
        if token != "AUTO":
            if token not in {"RGGB", "BGGR", "GRBG", "GBRG"}:
                raise ValueError("bayer_pattern must be one of: auto, RGGB, BGGR, GRBG, GBRG")
            return token

        cfa = self.cfa_code
        mapping = {
            0: None,  # CFA_NONE
            1: "GBRG",  # CFA_VRI (gbrg/rggb variants; best-effort default)
            2: "BGGR",  # CFA_VRIV6 (bggr/grbg variants; best-effort default)
            3: "GBRG",  # CFA_BAYER (gb/rg)
            4: "RGGB",  # CFA_BAYERFLIP (rg/gb)
            5: "GRBG",  # CFA_BAYERFLIPB (gr/bg variant)
            6: "BGGR",  # CFA_BAYERFLIPH (bg/gr)
        }
        return mapping.get(cfa, None)

    def _resolve_dead_value(self, dead_value: int | None) -> int:
        """Infer dead-pixel threshold from setup metadata when not provided."""
        if dead_value is not None:
            return int(dead_value)

        setup = self._require_camera_setup()
        white_level = int(getattr(setup, "WhiteLevel", -1))
        if white_level >= 0:
            if int(self._require_image_header().biCompression) == 256 and white_level < 1024:
                from ._lookup import LOOKUP_TABLE

                white_level = int(LOOKUP_TABLE[white_level])
            return white_level + 1

        real_bpp = int(getattr(setup, "RealBPP", 0))
        if real_bpp > 0:
            return (1 << real_bpp) - 1

        frame = self._require_pixel_array()
        if np.issubdtype(frame.dtype, np.integer):
            return int(np.iinfo(frame.dtype).max)
        return 4095

    @staticmethod
    def _decode_recording_datetime(trigger_time: int, recording_tz_seconds: int) -> datetime | None:
        """Decode CINE `TriggerTime` token to timezone-aware datetime when possible."""
        seconds = int(trigger_time >> 32)
        frac = int(trigger_time & 0xFFFFFFFF)
        if seconds <= 0:
            return None

        try:
            dt_utc = datetime.fromtimestamp(seconds, tz=timezone.utc)
        except (OverflowError, OSError, ValueError):
            return None

        micros = int(round((frac / float(1 << 32)) * 1_000_000.0))
        if micros >= 1_000_000:
            dt_utc += timedelta(seconds=1)
            micros -= 1_000_000
        dt_utc = dt_utc.replace(microsecond=micros)

        if abs(int(recording_tz_seconds)) >= 24 * 60 * 60:
            return dt_utc
        tzinfo = timezone(timedelta(seconds=-int(recording_tz_seconds)))
        return dt_utc.astimezone(tzinfo)

    def _require_file_handle(self) -> NativeReader:
        if self.file_handle is None:
            raise RuntimeError("No CINE file is open.")
        return self.file_handle

    def _require_file_header(self) -> CineHeader:
        if self.file_header is None:
            raise RuntimeError("File header is not loaded.")
        return self.file_header

    def _require_image_header(self) -> BitmapHeader:
        if self.image_header is None:
            raise RuntimeError("Image header is not loaded.")
        return self.image_header

    def _require_camera_setup(self) -> Setup:
        if self.camera_setup is None:
            raise RuntimeError("Camera setup is not loaded.")
        return self.camera_setup

    def _require_image_locations(self) -> ImageOffsets:
        if self.image_locations is None:
            raise RuntimeError("Image offsets are not loaded.")
        return self.image_locations

    def _require_pixel_array(self) -> np.ndarray:
        if self.pixel_array is None:
            raise RuntimeError("No frame loaded.")
        return self.pixel_array
