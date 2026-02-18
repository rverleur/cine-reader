"""Image-space operations for CINE frame arrays."""

from __future__ import annotations

import numpy as np



def replace_dead_pixels_mono(frame: np.ndarray, dead_value: int = 4095) -> np.ndarray:
    """Replace dead pixels in a mono frame using valid 8-neighbor mean.

    Parameters
    ----------
    frame:
        2D mono image.
    dead_value:
        Pixel value marking dead sensor sites.

    Returns
    -------
    numpy.ndarray
        Corrected frame with same dtype as input.
    """
    if frame.ndim != 2:
        return frame

    frame_f = frame.astype(np.float32, copy=False)
    dead_mask = frame == dead_value
    if not np.any(dead_mask):
        return frame

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
