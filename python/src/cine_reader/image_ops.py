"""Image-space operations for CINE frame arrays."""

from __future__ import annotations

import numpy as np


_NEIGHBOR_OFFSETS = (
    (-1, -1), (-1, 0), (-1, 1),
    (0, -1),           (0, 1),
    (1, -1),  (1, 0),  (1, 1),
)

_BAYER_PHASE_ROLES = {
    "RGGB": ((0, 0, "R"), (0, 1, "G_R"), (1, 0, "G_B"), (1, 1, "B")),
    "BGGR": ((0, 0, "B"), (0, 1, "G_B"), (1, 0, "G_R"), (1, 1, "R")),
    "GRBG": ((0, 0, "G_R"), (0, 1, "R"), (1, 0, "B"), (1, 1, "G_B")),
    "GBRG": ((0, 0, "G_B"), (0, 1, "B"), (1, 0, "R"), (1, 1, "G_R")),
}


def _bayer_phase_roles(pattern: str) -> tuple[tuple[int, int, str], ...]:
    token = pattern.upper()
    try:
        return _BAYER_PHASE_ROLES[token]
    except KeyError as exc:
        raise ValueError(f"Unsupported Bayer pattern: {pattern}") from exc


def _dead_mask(frame: np.ndarray, dead_value: int, *, dead_is_threshold: bool) -> np.ndarray:
    if dead_is_threshold:
        return frame >= dead_value
    return frame == dead_value


def _repair_sparse_dead_pixels(frame: np.ndarray, dead_mask: np.ndarray, out: np.ndarray) -> None:
    """Repair sparse dead pixels into `out` from valid 8-neighbor values."""
    y_bad, x_bad = np.nonzero(dead_mask)
    if y_bad.size == 0:
        return

    height, width = frame.shape
    sums = np.zeros(y_bad.size, dtype=np.float32)
    counts = np.zeros(y_bad.size, dtype=np.uint8)

    for row_offset, col_offset in _NEIGHBOR_OFFSETS:
        y_nbr = y_bad + row_offset
        x_nbr = x_bad + col_offset
        in_bounds = (y_nbr >= 0) & (y_nbr < height) & (x_nbr >= 0) & (x_nbr < width)
        if not np.any(in_bounds):
            continue

        idx = np.nonzero(in_bounds)[0]
        y_valid = y_nbr[idx]
        x_valid = x_nbr[idx]
        valid = ~dead_mask[y_valid, x_valid]
        if not np.any(valid):
            continue

        valid_idx = idx[valid]
        sums[valid_idx] += frame[y_valid[valid], x_valid[valid]]
        counts[valid_idx] += 1

    replace = counts > 0
    if np.any(replace):
        out[y_bad[replace], x_bad[replace]] = (sums[replace] / counts[replace]).astype(frame.dtype, copy=False)


def _replace_dead_pixels_dense_mask(frame: np.ndarray, dead_mask: np.ndarray) -> np.ndarray:
    """Dense vectorized repair path for images with many dead pixels."""
    if frame.ndim != 2:
        return frame

    frame_f = frame.astype(np.float32, copy=False)
    valid = ~dead_mask
    values = np.where(valid, frame_f, 0.0)
    valid_i = valid.astype(np.int16)

    pv = np.pad(values, ((1, 1), (1, 1)), mode="constant", constant_values=0.0)
    pm = np.pad(valid_i, ((1, 1), (1, 1)), mode="constant", constant_values=0)

    nbr_sum = (
        pv[:-2, :-2] + pv[:-2, 1:-1] + pv[:-2, 2:] +
        pv[1:-1, :-2] +                 pv[1:-1, 2:] +
        pv[2:, :-2] + pv[2:, 1:-1] + pv[2:, 2:]
    )
    nbr_cnt = (
        pm[:-2, :-2] + pm[:-2, 1:-1] + pm[:-2, 2:] +
        pm[1:-1, :-2] +                 pm[1:-1, 2:] +
        pm[2:, :-2] + pm[2:, 1:-1] + pm[2:, 2:]
    )

    out = frame_f.copy()
    replace_mask = dead_mask & (nbr_cnt > 0)
    out[replace_mask] = nbr_sum[replace_mask] / nbr_cnt[replace_mask]
    return out.astype(frame.dtype, copy=False)


def _replace_dead_pixels_mono_mask(frame: np.ndarray, dead_mask: np.ndarray) -> np.ndarray:
    """Replace dead pixels in a 2D image from a precomputed dead-pixel mask."""
    if frame.ndim != 2:
        return frame
    if dead_mask.shape != frame.shape:
        raise ValueError("dead_mask must have the same shape as frame")

    dead_count = int(np.count_nonzero(dead_mask))
    if dead_count == 0:
        return frame

    if dead_count <= max(64, frame.size // 25):
        out = frame.copy()
        _repair_sparse_dead_pixels(frame, dead_mask, out)
        return out

    return _replace_dead_pixels_dense_mask(frame, dead_mask)


def replace_dead_pixels_mono(
    frame: np.ndarray,
    dead_value: int = 4095,
    *,
    dead_is_threshold: bool = False,
) -> np.ndarray:
    """Replace dead pixels in a mono frame using valid 8-neighbor mean.

    Parameters
    ----------
    frame:
        2D mono image.
    dead_value:
        Dead-pixel marker value or threshold.
    dead_is_threshold:
        If `False`, dead pixels are `frame == dead_value`.
        If `True`, dead pixels are `frame >= dead_value`.
    """
    if frame.ndim != 2:
        return frame
    mask = _dead_mask(frame, dead_value, dead_is_threshold=dead_is_threshold)
    return _replace_dead_pixels_mono_mask(frame, mask)


def replace_dead_pixels_bayer(
    frame: np.ndarray,
    dead_value: int = 4095,
    *,
    dead_is_threshold: bool = False,
) -> np.ndarray:
    """Repair dead pixels in raw Bayer/CFA frame by processing each 2x2 phase separately.

    This follows the CINE guidance for raw color cines: bad pixels are not repaired in
    camera output and should be repaired in software before demosaic. Splitting by 2x2
    phase preserves color consistency of the CFA mosaic.
    """
    if frame.ndim != 2:
        return frame

    dead_mask = _dead_mask(frame, dead_value, dead_is_threshold=dead_is_threshold)
    dead_count = int(np.count_nonzero(dead_mask))
    if dead_count == 0:
        return frame

    if dead_count <= max(64, frame.size // 25):
        out = frame.copy()
        for row_phase in (0, 1):
            for col_phase in (0, 1):
                _repair_sparse_dead_pixels(
                    frame[row_phase::2, col_phase::2],
                    dead_mask[row_phase::2, col_phase::2],
                    out[row_phase::2, col_phase::2],
                )
        return out

    out = frame.copy()
    for row_phase in (0, 1):
        for col_phase in (0, 1):
            sub = frame[row_phase::2, col_phase::2]
            mask = dead_mask[row_phase::2, col_phase::2]
            out[row_phase::2, col_phase::2] = _replace_dead_pixels_mono_mask(sub, mask)
    return out


def replace_dead_pixels_rgb(
    frame: np.ndarray,
    dead_value: int = 4095,
    *,
    dead_is_threshold: bool = False,
) -> np.ndarray:
    """Repair dead pixels per channel in RGB/BGR image data."""
    if frame.ndim != 3:
        return frame
    if frame.shape[-1] <= 1:
        return frame.reshape(frame.shape[:2])

    out = frame.copy()
    for ch in range(frame.shape[-1]):
        channel = frame[..., ch]
        mask = _dead_mask(channel, dead_value, dead_is_threshold=dead_is_threshold)
        out[..., ch] = _replace_dead_pixels_mono_mask(channel, mask)
    return out


def replace_dead_pixels(
    frame: np.ndarray,
    *,
    dead_value: int = 4095,
    dead_is_threshold: bool = False,
    bayer_raw: bool = False,
) -> np.ndarray:
    """Dispatch dead-pixel repair for mono, Bayer raw, and RGB data.

    Parameters
    ----------
    frame:
        Input image array (2D mono/Bayer or 3D RGB/BGR).
    dead_value:
        Dead-pixel marker value or threshold.
    dead_is_threshold:
        If `True`, treat values `>= dead_value` as dead.
    bayer_raw:
        If `True` and `frame` is 2D, process as CFA mosaic by 2x2 phase.
    """
    if frame.ndim == 3:
        return replace_dead_pixels_rgb(
            frame,
            dead_value=dead_value,
            dead_is_threshold=dead_is_threshold,
        )
    if frame.ndim == 2 and bayer_raw:
        return replace_dead_pixels_bayer(
            frame,
            dead_value=dead_value,
            dead_is_threshold=dead_is_threshold,
        )
    return replace_dead_pixels_mono(
        frame,
        dead_value=dead_value,
        dead_is_threshold=dead_is_threshold,
    )


def demosaic_bilinear(frame: np.ndarray, pattern: str = "RGGB") -> np.ndarray:
    """Fast bilinear Bayer demosaic for mono raw frames."""
    input_dtype = frame.dtype
    frame_f = frame.astype(np.float32, copy=False)
    h, w = frame_f.shape

    pad = np.pad(frame_f, ((1, 1), (1, 1)), mode="edge")
    c = pad[1:-1, 1:-1]
    up = pad[:-2, 1:-1]
    dn = pad[2:, 1:-1]
    lf = pad[1:-1, :-2]
    rt = pad[1:-1, 2:]
    ul = pad[:-2, :-2]
    ur = pad[:-2, 2:]
    dl = pad[2:, :-2]
    dr = pad[2:, 2:]

    g_cross = (up + dn + lf + rt) * 0.25
    rb_diag = (ul + ur + dl + dr) * 0.25
    lr = (lf + rt) * 0.5
    ud = (up + dn) * 0.5

    rgb = np.empty((h, w, 3), dtype=np.float32)
    for row_phase, col_phase, role in _bayer_phase_roles(pattern):
        rows = slice(row_phase, None, 2)
        cols = slice(col_phase, None, 2)
        if role == "R":
            rgb[rows, cols, 0] = c[rows, cols]
            rgb[rows, cols, 1] = g_cross[rows, cols]
            rgb[rows, cols, 2] = rb_diag[rows, cols]
        elif role == "B":
            rgb[rows, cols, 0] = rb_diag[rows, cols]
            rgb[rows, cols, 1] = g_cross[rows, cols]
            rgb[rows, cols, 2] = c[rows, cols]
        elif role == "G_R":
            rgb[rows, cols, 0] = lr[rows, cols]
            rgb[rows, cols, 1] = c[rows, cols]
            rgb[rows, cols, 2] = ud[rows, cols]
        else:
            rgb[rows, cols, 0] = ud[rows, cols]
            rgb[rows, cols, 1] = c[rows, cols]
            rgb[rows, cols, 2] = lr[rows, cols]

    np.rint(rgb, out=rgb)
    return rgb.astype(input_dtype, copy=False)
