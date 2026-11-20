"""Use Rust-backed repair, demosaicing and statistics on NumPy arrays without a CINE file."""

from __future__ import annotations

import numpy as np

from cine_reader import (
    average_from_frame_iter,
    demosaic_bilinear,
    replace_dead_pixels,
    robust_background_mad_stack,
    robust_background_topk,
)


def process_arrays(*, frame_count: int, dead_value: int, bayer_pattern: str) -> None:
    mosaic = np.full((12, 16), 1000, dtype=np.uint16)
    mosaic[4, 6] = dead_value
    repaired = replace_dead_pixels(
        mosaic, dead_value=dead_value, dead_is_threshold=False, bayer_raw=True
    )
    rgb = demosaic_bilinear(repaired, pattern=bayer_pattern)
    print("Original / repaired sample:", mosaic[4, 6], repaired[4, 6])
    print("Demosaiced image:", rgb.shape, rgb.dtype)

    def frames():
        for number in range(frame_count):
            frame = repaired.copy()
            frame[number % frame.shape[0], :] = 100  # Moving dark object.
            yield frame

    mean, count = average_from_frame_iter(frames(), out_dtype=np.float64)
    bright = robust_background_topk(frames(), frame_count=frame_count, max_keep=4)
    # Use MAD only for manageable sequences: it retains all samples internally.
    mad = robust_background_mad_stack(frames())
    print(f"Mean over {count} frames: {mean.mean():.2f}")
    print("Bright background / MAD means:", float(bright.mean()), float(mad.mean()))


if __name__ == "__main__":
    number_of_frames = 12
    dead_pixel_marker = 4095
    sensor_pattern = "RGGB"

    process_arrays(
        frame_count=number_of_frames,
        dead_value=dead_pixel_marker,
        bayer_pattern=sensor_pattern,
    )
