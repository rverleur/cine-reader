"""Trim a cine file and compute robust background."""

from __future__ import annotations

from pathlib import Path

from cine_reader import Cine


def main() -> None:
    cine_path = Path(__file__).resolve().parents[2] / "sample_data" / "TrimmedCine.cine"
    cine = Cine(cine_path)
    first = cine.first_frame_number
    end = min(first + 20, cine.last_frame_number)

    cine.save_frames_to_new_file("trimmed_20_frames.cine", first, end)
    bg = cine.mode_frames(first, end, method="topk")
    print("Background image:", bg.shape, bg.dtype, int(bg.min()), int(bg.max()))

    cine.close_file()


if __name__ == "__main__":
    main()
