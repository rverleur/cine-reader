"""Read metadata and a few frames; set the input path in the IDE configuration below."""

from __future__ import annotations

from pathlib import Path

from cine_reader import Cine


def inspect_recording(
    cine_path: Path, *, remove_dead_pixels: bool, debayer: bool, preview_count: int
) -> None:
    """Keep individual frames in memory and demonstrate an explicitly small batch."""
    if preview_count <= 0:
        raise ValueError("preview_count must be positive")
    with Cine(
        cine_path,
        canonical=True,
        remove_dead_pixels=remove_dead_pixels,
        debayer=debayer,
    ) as cine:
        first = cine.first_frame_number
        print(f"Frames: {cine.total_frames} ({first}..{cine.last_frame_number})")
        print(f"Size: {cine.image_header.biWidth} x {abs(cine.image_header.biHeight)}")
        print(f"Rate: {cine.frame_rate:g} Hz; exposure: {cine.exposure_time_seconds:g} s")
        print(f"Recorded: {cine.recording_datetime}; Bayer pattern: {cine.bayer_pattern}")

        # Construction reads metadata; first access to image decodes the first frame.
        first_image = cine.image
        print("First frame:", first_image.shape, first_image.dtype)
        count = min(preview_count, cine.total_frames)
        for number in range(first, first + count):
            cine.load_frame(number)  # Acquisition numbers may start below zero.
            print(f"Frame {number}: min={cine.image.min()}, max={cine.image.max()}")
        # A previously returned array owns its pixels and survives subsequent loads.
        print("Retained first frame:", first_image.shape)

        if cine.bayer_pattern is not None or cine.image.ndim == 3:
            rgb = cine.get_frame_rgb(first)
            print("RGB image:", rgb.shape, rgb.dtype)

        # This API deliberately allocates a stack; keep count small for large images.
        batch = cine.load_frames_batch(first, count)
        print("Small batch (frame axis last):", batch.shape)
        print("Current annotation bytes:", len(cine.annotation_data))


if __name__ == "__main__":
    cine_file = Path("capture.cine")  # Set this to your recording.
    repair_dead_pixels = False
    demosaic_on_load = False
    number_of_sample_frames = 3

    inspect_recording(
        cine_file,
        remove_dead_pixels=repair_dead_pixels,
        debayer=demosaic_on_load,
        preview_count=number_of_sample_frames,
    )
