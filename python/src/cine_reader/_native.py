"""Private ctypes binding for the versioned, shared Rust CINE ABI."""

from __future__ import annotations

import ctypes as ct
import io
import os
import threading
from functools import lru_cache
from pathlib import Path

import numpy as np

from ._binary import BinaryError, select_prebuilt, validate_library


class CineInfo(ct.Structure):
    _fields_ = [
        ("width", ct.c_uint32),
        ("height", ct.c_int32),
        ("bit_count", ct.c_uint32),
        ("compression", ct.c_uint32),
        ("real_bpp", ct.c_uint32),
        ("cfa", ct.c_uint32),
        ("frame_count", ct.c_uint32),
        ("first_frame", ct.c_int32),
        ("channels", ct.c_uint32),
        ("sample_bytes", ct.c_uint32),
        ("decoded_bytes", ct.c_uint64),
        ("file_size", ct.c_uint64),
    ]


class FrameInfo(ct.Structure):
    _fields_ = [("annotation_size", ct.c_uint32), ("image_size", ct.c_uint32)]


class WriterOptions(ct.Structure):
    _fields_ = [
        (name, ct.c_uint32)
        for name in ("width", "height", "channels", "bit_depth", "packed10", "frame_count")
    ] + [("first_frame", ct.c_int32), ("cfa", ct.c_uint32), ("frame_rate", ct.c_double)]


def _path(path) -> bytes:
    return str(Path(path)).encode("utf-8")


@lru_cache(maxsize=1)
def library() -> ct.CDLL:
    override = os.environ.get("CINE_READER_LIBRARY")
    source = Path(__file__).resolve()
    try:
        if override:
            path = Path(override)  # Explicit maintainer/test override, still ABI-checked below.
        elif (source.parents[3] / "rust/cine-core/Cargo.toml").is_file():
            root = source.parents[3]
            try:
                path, _ = validate_library(source.parent / "libs", root)
            except BinaryError:
                path, _ = select_prebuilt(root)
        else:
            path, _ = validate_library(source.parent / "libs")
        try:
            lib = ct.CDLL(str(path))
        except OSError as exc:
            raise BinaryError(f"Cannot load the native CINE backend {path}: {exc}") from exc
    except BinaryError as exc:
        raise ImportError(str(exc)) from exc
    p, z, u, i, b = ct.c_void_p, ct.c_size_t, ct.c_uint32, ct.c_int32, ct.c_char_p
    signatures = {
        "cine_abi_version": (u, []),
        "cine_last_error": (b, []),
        "cine_reader_open": (p, [b]),
        "cine_reader_close": (None, [p]),
        "cine_reader_info": (i, [p, ct.POINTER(CineInfo)]),
        "cine_reader_offset": (i, [p, u, ct.POINTER(ct.c_uint64)]),
        "cine_reader_block": (i, [p, u, p, z, ct.POINTER(z)]),
        "cine_reader_read_at": (i, [p, ct.c_uint64, p, z]),
        "cine_reader_read_frame": (i, [p, u, u, p, z, ct.POINTER(FrameInfo)]),
        "cine_reader_trim": (i, [p, b, u, u]),
        "cine_decode": (i, [p, z, u, i, u, u, u, p, z]),
        "cine_unpack10": (i, [p, z, p, z]),
        "cine_writer_create": (p, [b, ct.POINTER(WriterOptions)]),
        "cine_writer_write": (i, [p, p, z]),
        "cine_writer_write_image": (i, [p, p, z, u, u]),
        "cine_writer_finish": (i, [p]),
        "cine_writer_close": (None, [p]),
        "cine_process": (i, [p, p, u, u, u, u, u, u, ct.c_double]),
        "cine_stats_create": (p, [z, u, u, ct.c_double, ct.c_double, u]),
        "cine_stats_push": (i, [p, p, z]),
        "cine_stats_finish": (i, [p, p, z, ct.POINTER(ct.c_uint64)]),
        "cine_stats_close": (None, [p]),
    }
    for symbol, (result, args) in signatures.items():
        function = getattr(lib, symbol)
        function.restype, function.argtypes = result, args
    if lib.cine_abi_version() != 1:
        raise ImportError("Incompatible Rust CINE ABI; rebuild or reinstall cine-handler")
    return lib


def check(status: int, lib=None) -> None:
    if status != 0:
        raw = (lib or library()).cine_last_error()
        message = raw.decode("utf-8", errors="replace") if raw else "Unknown CINE backend error"
        raise ValueError(message)


class NativeReader(io.RawIOBase):
    """Own the Rust handle and expose legacy file-like metadata access."""

    def __init__(self, filename):
        super().__init__()
        self.lib = library()
        self._lock = threading.RLock()
        self._handle = self.lib.cine_reader_open(_path(filename))
        if not self._handle:
            check(-1, self.lib)
        self.info = CineInfo()
        check(self.lib.cine_reader_info(self._handle, ct.byref(self.info)), self.lib)
        self._position = 0

    def _require_open(self):
        if not self._handle:
            raise ValueError("I/O operation on closed CINE file")

    def block(self, kind: int) -> bytes:
        with self._lock:
            self._require_open()
            length = ct.c_size_t()
            check(
                self.lib.cine_reader_block(self._handle, kind, None, 0, ct.byref(length)), self.lib
            )
            output = ct.create_string_buffer(length.value)
            check(
                self.lib.cine_reader_block(
                    self._handle, kind, output, length.value, ct.byref(length)
                ),
                self.lib,
            )
            return output.raw[: length.value]

    def offset(self, index: int) -> int:
        if index < 0 or index > self.info.frame_count:
            raise IndexError("Image offset index out of bounds")
        with self._lock:
            self._require_open()
            value = ct.c_uint64()
            check(self.lib.cine_reader_offset(self._handle, index, ct.byref(value)), self.lib)
            return value.value

    def load(self, index: int, *, flags: int = 0, annotations: bool = False):
        if index < 0 or index >= self.info.frame_count:
            raise IndexError("image_no is out of bounds")
        shape = (abs(self.info.height), self.info.width)
        if self.info.channels != 1:
            shape += (self.info.channels,)
        frame = np.empty(shape, dtype=np.uint8 if self.info.sample_bytes == 1 else "<u2")
        details = FrameInfo()
        with self._lock:
            self._require_open()
            check(
                self.lib.cine_reader_read_frame(
                    self._handle, index, flags, frame.ctypes.data, frame.nbytes, ct.byref(details)
                ),
                self.lib,
            )
            annotation = self.block(3) if annotations else b""
        return frame, details, annotation

    def trim(self, filename, index: int, count: int):
        with self._lock:
            self._require_open()
            check(self.lib.cine_reader_trim(self._handle, _path(filename), index, count), self.lib)

    def read(self, size: int = -1) -> bytes:
        with self._lock:
            self._require_open()
            available = max(0, self.info.file_size - self._position)
            size = available if size is None or size < 0 else min(int(size), available)
            output = ct.create_string_buffer(size)
            check(
                self.lib.cine_reader_read_at(self._handle, self._position, output, size), self.lib
            )
            self._position += size
            return output.raw

    def seek(self, offset: int, whence: int = 0) -> int:
        with self._lock:
            self._require_open()
            base = (
                0
                if whence == 0
                else self._position
                if whence == 1
                else self.info.file_size
                if whence == 2
                else None
            )
            if base is None or base + offset < 0:
                raise ValueError("Invalid seek")
            self._position = int(base + offset)
            return self._position

    def tell(self) -> int:
        return self._position

    def readable(self):
        return True

    def seekable(self):
        return True

    def close(self):
        lock = getattr(self, "_lock", None)
        if lock is not None:
            with lock:
                handle, self._handle = getattr(self, "_handle", None), None
                if handle:
                    self.lib.cine_reader_close(handle)
        super().close()


class NativeWriter:
    def __init__(self, filename, **options):
        for name in ("width", "height", "channels", "bit_depth", "frame_count", "cfa"):
            if not 0 <= options[name] <= 0xFFFFFFFF:
                raise ValueError(f"{name} is outside the uint32 range")
        if not -(1 << 31) <= options["first_frame"] < (1 << 31):
            raise ValueError("first_frame is outside the int32 range")
        self.lib = library()
        self._lock = threading.RLock()
        config = WriterOptions(**options)
        self._handle = self.lib.cine_writer_create(_path(filename), ct.byref(config))
        if not self._handle:
            check(-1, self.lib)

    def write_frame(self, frame: np.ndarray):
        with self._lock:
            if not self._handle:
                raise RuntimeError("CINE writer is closed")
            check(
                self.lib.cine_writer_write_image(
                    self._handle,
                    frame.ctypes.data,
                    frame.nbytes,
                    frame.dtype.itemsize,
                    frame.shape[2] if frame.ndim == 3 else 1,
                ),
                self.lib,
            )

    def finish(self):
        with self._lock:
            if not self._handle:
                raise RuntimeError("CINE writer is closed")
            check(self.lib.cine_writer_finish(self._handle), self.lib)

    def close(self):
        lock = getattr(self, "_lock", None)
        if lock is not None:
            with lock:
                handle, self._handle = getattr(self, "_handle", None), None
                if handle:
                    self.lib.cine_writer_close(handle)

    def __del__(self):
        self.close()
