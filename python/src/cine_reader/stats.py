"""Streaming NumPy adapters for Rust-owned statistics accumulators."""

from __future__ import annotations

import ctypes as ct
import math
from typing import Iterable

import numpy as np

from ._native import check, library


def _statistics(frames, *, mode, k=1, q=0.8, sigma=2.5, min_keep=3, out_dtype=None):
    lib = library()
    handle = None
    shape = None
    dtype = out_dtype
    try:
        for frame in frames:
            array = np.asarray(frame)
            if shape is None:
                shape = array.shape
                dtype = array.dtype if dtype is None else dtype
                if array.size == 0:
                    raise ValueError("Frames must contain at least one sample")
                handle = lib.cine_stats_create(array.size, mode, k, q, sigma, min_keep)
                if not handle:
                    check(-1, lib)
            elif array.shape != shape:
                raise ValueError("All frames must have the same shape")
            values = np.ascontiguousarray(array, dtype=np.float64)
            check(lib.cine_stats_push(handle, values.ctypes.data, values.size), lib)
        if handle is None:
            raise RuntimeError("No frames were provided.")
        result = np.empty(shape, dtype=np.float64)
        count = ct.c_uint64()
        check(lib.cine_stats_finish(handle, result.ctypes.data, result.size, ct.byref(count)), lib)
        return result.astype(dtype, copy=False), count.value
    finally:
        if handle:
            lib.cine_stats_close(handle)


def average_from_frame_iter(
    frames: Iterable[np.ndarray], *, out_dtype: np.dtype | None = None, chunk_size: int = 8
) -> tuple[np.ndarray, int]:
    """Mean using one Rust accumulator; chunk_size remains accepted for compatibility."""
    if chunk_size <= 0:
        raise ValueError("chunk_size must be > 0")
    return _statistics(frames, mode=0, out_dtype=out_dtype)


def robust_background_mad_stack(
    frames: Iterable[np.ndarray],
    *,
    q_bg: float = 0.80,
    k_sigma: float = 2.5,
    min_keep: int = 3,
    out_dtype: np.dtype = np.uint16,
) -> np.ndarray:
    """Quantile/MAD background estimate; its full sample stack is owned by Rust."""
    if not 0.0 < q_bg < 1.0:
        raise ValueError("q_bg must be between 0 and 1")
    if min_keep < 0 or min_keep > 0xFFFFFFFF:
        raise ValueError("min_keep is outside the uint32 range")
    return _statistics(
        frames, mode=2, q=q_bg, sigma=k_sigma, min_keep=min_keep, out_dtype=out_dtype
    )[0]


def robust_background_topk(
    frames: Iterable[np.ndarray],
    *,
    frame_count: int,
    q_bg: float = 0.80,
    min_keep: int = 3,
    max_keep: int | None = 96,
    out_dtype: np.dtype = np.uint16,
) -> np.ndarray:
    """Bounded-memory background estimate retaining the k brightest samples."""
    if frame_count <= 0:
        raise ValueError("frame_count must be > 0")
    if not 0.0 < q_bg < 1.0:
        raise ValueError("q_bg must be between 0 and 1")
    k_keep = max(min_keep, int(math.ceil((1.0 - q_bg) * frame_count)))
    if max_keep is not None:
        k_keep = min(k_keep, max_keep)
    k_keep = max(1, k_keep)
    if k_keep > 0xFFFFFFFF:
        raise ValueError("Too many retained samples")
    return _statistics(
        frames, mode=1, k=k_keep, q=q_bg, min_keep=max(0, min_keep), out_dtype=out_dtype
    )[0]
