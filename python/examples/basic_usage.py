"""Basic cine_reader usage example."""

from __future__ import annotations

from pathlib import Path

from cine_reader import Cine

import matplotlib.pyplot as plt

def main() -> None:
    cine_path = Path(__file__).resolve().parents[2] / "sample_data" / "TrimmedCine.cine"
    cine = Cine(cine_path)
    first = cine.first_frame_number
    last = cine.last_frame_number

    print(f"Frames: {cine.total_frames} ({first}..{last})")
    print(f"Resolution: {cine.image_header.biWidth} x {abs(cine.image_header.biHeight)}")
    print(f"Bit depth: biBitCount={cine.image_header.biBitCount}, RealBPP={cine.camera_setup.RealBPP}")
    print(f"Frame rate: {cine.frame_rate:.6f} Hz")
    print(f"Exposure time: {cine.exposure_time_seconds:.9f} s")
    print(f"Recording date: {cine.recording_date}")

    cine.load_frame(first)
    print("Loaded frame shape:", cine.frame.shape, cine.frame.dtype)

    avg = cine.average_frames(first, min(first + 9, last))
    print("Average frame:", avg.shape, avg.dtype)

    rgb = cine.get_frame_rgb(first)
    print("RGB frame:", rgb.shape, rgb.dtype)

    cine.replace_dead_pixels()
    plt.imshow(cine.frame, cmap="gray")
    plt.show()

    cine.close_file()

if __name__ == "__main__":
    main()
