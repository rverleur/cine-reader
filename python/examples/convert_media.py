"""Convert image files or a video to CINE using Python packages only.

Install cine-handler[media], then select inputs in the IDE configuration below.
Images are decoded in the supplied order; video is decoded one frame at a time.
"""

from __future__ import annotations

from pathlib import Path

from cine_reader import Cine, write_cine_from_images, write_cine_from_video


def convert_media(
    *,
    image_paths: list[Path],
    video_path: Path | None,
    output_directory: Path,
    encoding: str,
    image_frame_rate: float,
    video_frame_rate: float | None,
    grayscale_video: bool,
) -> list[Path]:
    if not image_paths and video_path is None:
        raise ValueError("Configure image_paths or video_path in the __main__ block")
    output_directory.mkdir(parents=True, exist_ok=True)
    outputs = []
    if image_paths:
        outputs.append(
            write_cine_from_images(
                output_directory / "images.cine",
                image_paths,
                frame_rate=image_frame_rate,
                encoding=encoding,
            )
        )
    if video_path is not None:
        outputs.append(
            write_cine_from_video(
                output_directory / "video.cine",
                video_path,
                frame_rate=video_frame_rate,
                grayscale=grayscale_video,
                encoding=encoding,
            )
        )
    for output in outputs:
        with Cine(output, canonical=True) as cine:
            print(f"{output.resolve()}: {cine.total_frames} frames at {cine.frame_rate:g} Hz")
            print("First decoded frame:", cine.image.shape, cine.image.dtype)
    return outputs


if __name__ == "__main__":
    # Zero-padded names (frame_0001.png) keep lexical sorting in acquisition order.
    ordered_images = sorted(Path("input_images").glob("*.png"))
    video_file = None  # Set to Path("input.mp4") to convert a video too/instead.
    output_folder = Path("converted_cines")  # Existing output files are rejected.
    output_encoding = "normal"  # Or "packed10" (lossy, RGB becomes a Bayer mosaic).
    image_sequence_rate = 30.0
    video_rate_override = None  # Set a constant rate for variable-rate input.
    convert_video_to_gray = False

    converted_files = convert_media(
        image_paths=ordered_images,
        video_path=video_file,
        output_directory=output_folder,
        encoding=output_encoding,
        image_frame_rate=image_sequence_rate,
        video_frame_rate=video_rate_override,
        grayscale_video=convert_video_to_gray,
    )
