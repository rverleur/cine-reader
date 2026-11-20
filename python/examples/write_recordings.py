"""Create normal mono/RGB, packed10 and incremental CINE files from synthetic arrays.

Run directly from an IDE. Only NumPy and cine-handler are needed. Each run uses a
new temporary output directory by default and prints its location for inspection.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import numpy as np

from cine_reader import Cine, CineWriter, write_cine


def write_examples(output_directory: Path, *, frame_count: int, frame_rate: float) -> None:
    output_directory.mkdir(parents=True, exist_ok=True)
    # Writer stacks use a leading frame axis: [N,H,W] or [N,H,W,3].
    ramp = np.linspace(0, 4095, 32 * 48).reshape(32, 48).astype(np.uint16)
    mono = np.stack([np.roll(ramp, index, axis=1) for index in range(frame_count)])
    normal_path = write_cine(
        output_directory / "normal_mono.cine",
        mono,
        bit_depth=12,
        frame_rate=frame_rate,
        first_frame=-2,
    )
    with Cine(normal_path, canonical=True) as cine:
        np.testing.assert_array_equal(cine.image, mono[0])
        print("Normal mono preserved every sample; first frame:", cine.first_frame_number)

    rgb8 = np.stack((mono // 16, mono // 32, mono // 64), axis=-1).astype(np.uint8)
    rgb_path = write_cine(output_directory / "normal_rgb.cine", rgb8, frame_rate=frame_rate)
    with Cine(rgb_path, canonical=True) as cine:
        np.testing.assert_array_equal(cine.image, rgb8[0])

    # P10 maps linear12 samples to Phantom's nonlinear lookup table. It is lossy.
    packed_path = write_cine(
        output_directory / "packed10_mono.cine",
        mono,
        encoding="packed10",
        frame_rate=frame_rate,
    )
    with Cine(packed_path, canonical=True) as cine:
        error = np.abs(cine.image.astype(np.int32) - mono[0].astype(np.int32))
        print("Packed10 maximum first-frame quantization error:", int(error.max()))

    # RGB P10 stores one color sample per Bayer site, then needs demosaicing to RGB.
    color_path = write_cine(
        output_directory / "packed10_bayer.cine",
        rgb8,
        encoding="packed10",
        cfa=4,  # RGGB; 3=GBRG, 5=GRBG, 6=BGGR.
        frame_rate=frame_rate,
    )
    with Cine(color_path, canonical=True) as cine:
        print("Packed color raw/RGB shapes:", cine.image.shape, cine.get_frame_rgb().shape)

    # The incremental API retains a frame plus encoder buffers. An exact count
    # avoids the temporary disk spool required when frame_count=None.
    with CineWriter(
        output_directory / "incremental.cine",
        width=ramp.shape[1],
        height=ramp.shape[0],
        dtype=np.uint16,
        frame_count=frame_count,
        frame_rate=frame_rate,
    ) as writer:
        for index in range(frame_count):
            writer.write_frame(np.roll(ramp, index, axis=1))

    # A generator of unknown length is supported and uses bounded RAM plus disk.
    write_cine(
        output_directory / "unknown_length.cine",
        (np.roll(ramp, index, axis=0) for index in range(frame_count)),
        frame_rate=frame_rate,
    )
    print("Created six recordings in", output_directory.resolve())


if __name__ == "__main__":
    output_folder = Path(tempfile.mkdtemp(prefix="cine-writing-example-"))
    number_of_frames = 5
    acquisition_rate = 1000.0

    write_examples(output_folder, frame_count=number_of_frames, frame_rate=acquisition_rate)
