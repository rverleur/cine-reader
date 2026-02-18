"""Trim a cine file and compute robust background."""

from __future__ import annotations

from pathlib import Path

from cine_reader import Cine


def main() -> None:
    cine_path = Path(__file__).resolve().parents[2] / "sample_data" / "TrimmedCine.cine"
    cine = Cine(cine_path)
    first = cine.FileHeader.FirstImageNo
    end = min(first + 20, first + cine.FileHeader.ImageCount - 1)

    cine.SaveFramesToNewFile("trimmed_20_frames.cine", first, end)
    bg = cine.ModeFrames(first, end)
    print("Background image:", bg.shape, bg.dtype, int(bg.min()), int(bg.max()))

    cine.CloseFile()


if __name__ == "__main__":
    main()
