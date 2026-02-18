"""Frame statistics helpers with low-memory implementations."""

from __future__ import annotations

import math
from typing import Iterable

import numpy as np


def robust_background_mad_stack(
    frames: Iterable[np.ndarray],
    *,
    q_bg: float = 0.80,
    k_sigma: float = 2.5,
    min_keep: int = 3,
    out_dtype: np.dtype = np.uint16,
) -> np.ndarray:
    """Original quantile/MAD robust background estimator.

    This matches the previous behavior but stores the full frame stack.
    """
    if not (0.0 < q_bg < 1.0):
        raise ValueError("q_bg must be between 0 and 1")

    data = [np.asarray(frame, dtype=np.float32) for frame in frames]
    if not data:
        raise RuntimeError("No frames were provided.")
    if data[0].ndim != 2:
        raise ValueError("robust_background_mad_stack currently supports mono frames only")

    stack = np.stack(data, axis=0)
    bg = np.quantile(stack, q_bg, axis=0)
    med = np.median(stack, axis=0)
    mad = np.median(np.abs(stack - med[None, :, :]), axis=0)
    sigma = np.maximum(1.4826 * mad, 1e-6)
    keep = stack >= (bg[None, :, :] - k_sigma * sigma[None, :, :])
    num = np.sum(np.where(keep, stack, 0.0), axis=0)
    den = np.sum(keep, axis=0)
    out = np.divide(num, den, out=bg.copy(), where=(den >= min_keep))
    out = np.clip(np.rint(out), 0, np.iinfo(np.uint16).max)
    return out.astype(out_dtype, copy=False)


def average_from_frame_iter(
    frames: Iterable[np.ndarray],
    *,
    out_dtype: np.dtype | None = None,
    chunk_size: int = 8,
) -> tuple[np.ndarray, int]:
    """Compute per-pixel mean from a frame iterator.

    Uses chunked accumulation to reduce Python overhead while keeping memory bounded.

    Returns
    -------
    (avg, count)
        Averaged frame and number of frames consumed.
    """
    if chunk_size <= 0:
        raise ValueError("chunk_size must be > 0")

    acc = None
    count = 0
    pending = []
    resolved_dtype = out_dtype

    def flush_pending() -> None:
        nonlocal acc, count, pending, resolved_dtype
        if not pending:
            return
        stack = np.stack(pending, axis=0).astype(np.float64, copy=False)
        if acc is None:
            acc = np.zeros_like(stack[0], dtype=np.float64)
        acc += np.sum(stack, axis=0, dtype=np.float64)
        count += stack.shape[0]
        pending = []

    for frame in frames:
        arr = np.asarray(frame)
        if resolved_dtype is None:
            resolved_dtype = arr.dtype
        pending.append(arr)
        if len(pending) >= chunk_size:
            flush_pending()

    flush_pending()

    if acc is None or count == 0:
        raise RuntimeError("No frames were provided.")
    avg = np.rint(acc / count)
    return avg.astype(resolved_dtype), count



def robust_background_topk(
    frames: Iterable[np.ndarray],
    *,
    frame_count: int,
    q_bg: float = 0.80,
    min_keep: int = 3,
    max_keep: int | None = 96,
    out_dtype: np.dtype = np.uint16,
) -> np.ndarray:
    """Estimate bright background by keeping top-k samples per pixel.

    This is a low-memory alternative to full-stack quantile/MAD estimation.
    It is robust to dark occlusions and scales well for long sequences.
    """
    if frame_count <= 0:
        raise ValueError("frame_count must be > 0")
    if not (0.0 < q_bg < 1.0):
        raise ValueError("q_bg must be between 0 and 1")

    k_keep = max(min_keep, int(math.ceil((1.0 - q_bg) * frame_count)))
    if max_keep is not None:
        k_keep = min(k_keep, max_keep)
    k_keep = max(1, k_keep)

    topk = None
    rr = cc = None
    loaded = 0

    for frame in frames:
        arr = np.asarray(frame)
        if arr.ndim != 2:
            raise ValueError("robust_background_topk currently supports mono frames only")
        arr_f = arr.astype(np.float32, copy=False)

        if topk is None:
            h, w = arr_f.shape
            topk = np.full((k_keep, h, w), -np.inf, dtype=np.float32)
            rr, cc = np.indices((h, w))

        if loaded < k_keep:
            topk[loaded] = arr_f
        else:
            min_idx = np.argmin(topk, axis=0)
            min_vals = topk[min_idx, rr, cc]
            replace = arr_f > min_vals
            if np.any(replace):
                topk[min_idx[replace], rr[replace], cc[replace]] = arr_f[replace]
        loaded += 1

    if topk is None or loaded == 0:
        raise RuntimeError("No frames were provided.")

    used = min(loaded, k_keep)
    out = np.mean(topk[:used], axis=0)
    out = np.clip(np.rint(out), 0, np.iinfo(np.uint16).max)
    return out.astype(out_dtype, copy=False)
