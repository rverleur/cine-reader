"""Image-space operations for CINE frame arrays."""

from __future__ import annotations

import numpy as np


def _dead_mask(frame: np.ndarray, dead_value: int, *, dead_is_threshold: bool) -> np.ndarray:
    if dead_is_threshold:
        return frame >= dead_value
    return frame == dead_value


def _replace_dead_pixels_mono_mask(frame: np.ndarray, dead_mask: np.ndarray) -> np.ndarray:
    """Replace dead pixels in a 2D image from a precomputed dead-pixel mask."""
    if frame.ndim != 2:
        return frame
    if dead_mask.shape != frame.shape:
        raise ValueError("dead_mask must have the same shape as frame")
    if not np.any(dead_mask):
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

    out = frame.copy()
    for row_phase in (0, 1):
        for col_phase in (0, 1):
            sub = frame[row_phase::2, col_phase::2]
            mask = _dead_mask(sub, dead_value, dead_is_threshold=dead_is_threshold)
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
    yy, xx = np.indices((h, w))
    even_r = (yy % 2) == 0
    even_c = (xx % 2) == 0

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

    pattern = pattern.upper()
    if pattern == "RGGB":
        r_mask = even_r & even_c
        b_mask = (~even_r) & (~even_c)
        g_r_mask = even_r & (~even_c)
        g_b_mask = (~even_r) & even_c
    elif pattern == "BGGR":
        b_mask = even_r & even_c
        r_mask = (~even_r) & (~even_c)
        g_b_mask = even_r & (~even_c)
        g_r_mask = (~even_r) & even_c
    elif pattern == "GRBG":
        g_r_mask = even_r & even_c
        r_mask = even_r & (~even_c)
        b_mask = (~even_r) & even_c
        g_b_mask = (~even_r) & (~even_c)
    elif pattern == "GBRG":
        g_b_mask = even_r & even_c
        b_mask = even_r & (~even_c)
        r_mask = (~even_r) & even_c
        g_r_mask = (~even_r) & (~even_c)
    else:
        raise ValueError(f"Unsupported Bayer pattern: {pattern}")

    r = np.zeros_like(frame_f, dtype=np.float32)
    g = np.zeros_like(frame_f, dtype=np.float32)
    b = np.zeros_like(frame_f, dtype=np.float32)

    g_cross = (up + dn + lf + rt) * 0.25
    rb_diag = (ul + ur + dl + dr) * 0.25
    lr = (lf + rt) * 0.5
    ud = (up + dn) * 0.5

    r[r_mask] = c[r_mask]
    g[r_mask] = g_cross[r_mask]
    b[r_mask] = rb_diag[r_mask]

    b[b_mask] = c[b_mask]
    g[b_mask] = g_cross[b_mask]
    r[b_mask] = rb_diag[b_mask]

    g[g_r_mask] = c[g_r_mask]
    r[g_r_mask] = lr[g_r_mask]
    b[g_r_mask] = ud[g_r_mask]

    g[g_b_mask] = c[g_b_mask]
    r[g_b_mask] = ud[g_b_mask]
    b[g_b_mask] = lr[g_b_mask]

    rgb = np.stack((r, g, b), axis=-1)
    return np.rint(rgb).astype(input_dtype, copy=False)
