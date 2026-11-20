"""Trim without re-encoding and estimate mean/bright backgrounds from a recording."""

from __future__ import annotations

from pathlib import Path

from cine_reader import Cine


def trim_and_estimate(
    cine_path: Path,
    output_path: Path,
    *,
    start_frame: int | None,
    frame_count: int,
    max_background_samples: int,
) -> None:
    if frame_count <= 0:
        raise ValueError("frame_count must be positive")
    with Cine(cine_path, canonical=True) as cine:
        first = cine.first_frame_number if start_frame is None else start_frame
        last = min(first + frame_count - 1, cine.last_frame_number)
        mean = cine.average_frames(first, last)
        # topk retains bounded samples; method='mad' instead keeps the full stack.
        background = cine.mode_frames(first, last, method="topk", max_keep=max_background_samples)
        print("Mean:", mean.shape, mean.dtype, float(mean.mean()))
        print("Bright background:", background.shape, background.dtype)

        # Trim copies original encoded frames and preserves their acquisition numbers.
        # It does not bake the computed background or any image processing into output.
        output_path.parent.mkdir(parents=True, exist_ok=True)
        cine.save_frames_to_new_file(output_path, first, last)
    print("Trimmed recording:", output_path.resolve())


if __name__ == "__main__":
    cine_file = Path("capture.cine")
    trimmed_file = Path("trimmed.cine")  # Must not already exist.
    first_frame = None  # None uses the recording's first acquisition number.
    frames_to_use = 20
    retained_background_samples = 8

    trim_and_estimate(
        cine_file,
        trimmed_file,
        start_frame=first_frame,
        frame_count=frames_to_use,
        max_background_samples=retained_background_samples,
    )
