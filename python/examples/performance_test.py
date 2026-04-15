"""Measure CINE frame loading throughput.

Edit the configuration values in the `__main__` block and run this file from
your IDE. The timed section loads frames and copies each decoded array into a
preallocated NumPy stack, which is the common bottleneck for larger processing
pipelines.
"""

from __future__ import annotations

from pathlib import Path
from time import perf_counter

import numpy as np

from cine_reader import Cine


def benchmark_frame_loading(
    cine_path: str | Path,
    *,
    start_frame: int | None = None,
    frame_count: int = 1000,
    remove_dead_pixels: bool = False,
    debayer: bool = False,
) -> np.ndarray:
    """Load consecutive frames into memory and print throughput statistics."""
    with Cine(
        cine_path,
        remove_dead_pixels=remove_dead_pixels,
        debayer=debayer,
    ) as cine:
        first = cine.first_frame_number if start_frame is None else int(start_frame)
        count = min(int(frame_count), cine.last_frame_number - first + 1)
        if count <= 0:
            raise ValueError("Requested frame range is outside the cine.")

        # Load once before timing so allocation does not distort the frame loop.
        cine.load_frame(first)
        frames = np.empty(cine.frame.shape + (count,), dtype=cine.frame.dtype)

        start = perf_counter()
        for out_idx, frame_no in enumerate(range(first, first + count)):
            cine.load_frame(frame_no)
            frames[..., out_idx] = cine.frame
        elapsed = perf_counter() - start

    seconds_per_frame = elapsed / count
    frames_per_second = count / elapsed if elapsed > 0 else float("inf")
    mib_loaded = frames.nbytes / (1024 ** 2)
    mib_per_second = mib_loaded / elapsed if elapsed > 0 else float("inf")

    print(f"Loaded shape: {frames.shape}, dtype: {frames.dtype}")
    print(f"Timed frames: {count}")
    print(f"Total time: {elapsed:.3f} s")
    print(f"Time per frame: {seconds_per_frame * 1000:.3f} ms")
    print(f"Throughput: {frames_per_second:.2f} frames/s, {mib_per_second:.2f} MiB/s")

    return frames


if __name__ == "__main__":
    cine_file = Path("/Users/rverleur/Downloads/shot3_visible_shot_0_2500.cine")

    loaded_frames = benchmark_frame_loading(
        cine_file,
        frame_count=1000,
        remove_dead_pixels=True,
        debayer=True,
    )

    print(f"Array memory: {loaded_frames.nbytes / (1024 ** 2):.2f} MiB")
