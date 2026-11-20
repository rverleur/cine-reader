"""Time object opening and sequential decoding without retaining a video-sized stack.

Set the path and frame count in the IDE configuration at the bottom. Measurements
include Python dispatch; filesystem caching affects results. No GPU is required.
"""

from __future__ import annotations

from pathlib import Path
from time import perf_counter

from cine_reader import Cine


def benchmark_frame_loading(
    cine_path: Path,
    *,
    start_frame: int | None,
    frame_count: int,
    remove_dead_pixels: bool,
    debayer: bool,
) -> dict[str, float]:
    if frame_count <= 0:
        raise ValueError("frame_count must be positive")
    opened = perf_counter()
    with Cine(
        cine_path,
        canonical=True,
        remove_dead_pixels=remove_dead_pixels,
        debayer=debayer,
    ) as cine:
        open_seconds = perf_counter() - opened
        first = cine.first_frame_number if start_frame is None else start_frame
        if not cine.first_frame_number <= first <= cine.last_frame_number:
            raise ValueError("Requested start frame is outside the recording")
        count = min(frame_count, cine.last_frame_number - first + 1)

        # Warm native-library initialization separately from the sequential loop.
        cine.load_frame(first)
        bytes_per_frame = cine.image.nbytes
        started = perf_counter()
        for number in range(first, first + count):
            cine.load_frame(number)
        elapsed = perf_counter() - started

    result = {
        "open_ms": open_seconds * 1000,
        "frames_per_second": count / elapsed,
        "decoded_mib_per_second": count * bytes_per_frame / elapsed / 1024**2,
        "frame_mib": bytes_per_frame / 1024**2,
    }
    print(f"Decoded {count} frames in {elapsed:.3f} s")
    for name, value in result.items():
        print(f"{name}: {value:.3f}")
    return result


if __name__ == "__main__":
    cine_file = Path("capture.cine")
    first_frame = None
    frames_to_load = 1000
    repair_dead_pixels = False
    demosaic_on_load = False

    timings = benchmark_frame_loading(
        cine_file,
        start_frame=first_frame,
        frame_count=frames_to_load,
        remove_dead_pixels=repair_dead_pixels,
        debayer=demosaic_on_load,
    )
