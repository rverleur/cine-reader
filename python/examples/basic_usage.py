"""Basic cine_reader usage example."""

from __future__ import annotations

from pathlib import Path

from cine_reader import Cine


def main() -> None:
    cine_path = Path(__file__).resolve().parents[2] / "sample_data" / "TrimmedCine.cine"
    cine = Cine(cine_path)
    first = cine.FileHeader.FirstImageNo
    last = first + cine.FileHeader.ImageCount - 1

    print(f"Frames: {cine.FileHeader.ImageCount} ({first}..{last})")
    print(f"Resolution: {cine.ImageHeader.biWidth} x {abs(cine.ImageHeader.biHeight)}")
    print(f"Bit depth: biBitCount={cine.ImageHeader.biBitCount}, RealBPP={cine.CameraSetup.RealBPP}")

    cine.LoadFrame(first)
    print("Loaded frame shape:", cine.PixelArray.shape, cine.PixelArray.dtype)

    avg = cine.AverageFrames(first, min(first + 9, last))
    print("Average frame:", avg.shape, avg.dtype)

    rgb = cine.GetFrameRGB(first)
    print("RGB frame:", rgb.shape, rgb.dtype)

    cine.CloseFile()


if __name__ == "__main__":
    main()
