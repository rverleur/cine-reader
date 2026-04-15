# Python Package (`cine_reader`)

## Install

From GitHub:

```bash
pip install "git+https://github.com/<your-user>/<your-repo>.git"
```

From local checkout:

```bash
pip install -e .
```

## Quick Start

```python
from pathlib import Path
from cine_reader import Cine

cine_path = Path("sample_data/TrimmedCine.cine")

with Cine(cine_path) as cine:
    print(cine.total_frames)
    print(cine.first_frame_number, cine.last_frame_number)
    print(cine.frame_rate, cine.exposure_time_seconds)
    print(cine.recording_date)

    cine.load_frame(cine.first_frame_number)
    img = cine.image

    avg = cine.average_frames(cine.first_frame_number, cine.first_frame_number + 10)
    bg = cine.mode_frames(cine.first_frame_number, cine.first_frame_number + 20, method="auto")
    rgb = cine.get_frame_rgb()
```

## Main API

Primary methods use snake_case:

- `Cine(path, keep_annotations=True, remove_dead_pixels=False, debayer=False, dead_value=None, dead_is_threshold=True, bayer_pattern="auto")`
- `open_cine_file(path)`
- `load_frame(image_no, convert_bgr_to_rgb=False)`
- `next_frame(increment=1, convert_bgr_to_rgb=False)`
- `close_file()`
- `replace_dead_pixels(dead_value=None, dead_is_threshold=True)`
- `debayer_frame(bayer_pattern="auto")`
- `average_frames(start_frame, end_frame, replace_dead_pixels=False, chunk_size=8)`
- `mode_frames(start_frame, end_frame, replace_dead_pixels=False, method="auto", q_bg=0.80, k_sigma=2.5, min_keep=3, max_keep=96, stack_limit=128)`
- `load_frames_batch(start_frame, count)`
- `get_frame_rgb(image_no=None, bayer_pattern="auto")`
- `save_frames_to_new_file(output_filename, start_frame, end_frame)`

Top-level aliases for frequently used metadata:

- `first_frame_number`
- `total_frames`
- `last_frame_number`
- `frame_rate`
- `exposure_time_ns`
- `exposure_time_seconds` (alias: `exposure_time`)
- `recording_datetime`
- `recording_date`
- `cfa_code`
- `bayer_pattern`
- `image` / `frame` (aliases for latest pixel array)
- `red_pixels` / `green_pixels` / `blue_pixels` (raw CFA color samples with `NaN` at other sites)

Specification-aligned metadata blocks remain available:

- `file_header` (`CineHeader`) with CINE field names (`FirstImageNo`, `ImageCount`, ...)
- `image_header` (`BitmapHeader`) with `bi*` names (`biWidth`, `biBitCount`, ...)
- `camera_setup` (`Setup`) with setup field names (`FrameRate`, `ShutterNs`, `RealBPP`, ...)
- `image_locations` (`ImageOffsets`) with frame offsets (`pImage`)

## Module Layout

- `python/src/cine_reader/cine.py`: public `Cine` facade and file lifecycle.
- `python/src/cine_reader/headers.py`: dataclasses + binary parsing for header/setup/offset blocks.
- `python/src/cine_reader/frame_decode.py`: payload decode logic (8/16/24/48 and packed 10-bit).
- `python/src/cine_reader/image_ops.py`: dead-pixel replacement and Bayer demosaic utilities.
- `python/src/cine_reader/stats.py`: frame statistics (`average` and robust background estimators).
- `python/src/cine_reader/unpack.py`: native-library loading plus NumPy 10-bit fallback.

## Performance Hints

For large frame ranges:

- Use `mode_frames(..., method="topk")` for bounded-memory robust background estimation.
- Use `mode_frames(..., method="mad")` for quantile/MAD background estimation.
- Keep `replace_dead_pixels=False` unless dead-pixel correction is required.
- Reuse the same `Cine` object for repeated operations.
- Tune `average_frames(..., chunk_size=...)` for your memory/CPU balance.
- `mode_frames` now works on both mono and RGB frame stacks.

Frame loading and image processing follow the CINE format guidance:

- raw CFA/Bayer cines decode as 2D sensor mosaics by default, including packed 10-bit and normal 8/16-bit payloads
- pass `debayer=True` to debayer every loaded frame, or call `debayer_frame()` on the current frame
- pass `remove_dead_pixels=True` to repair dead pixels every time a frame is loaded
- raw CFA/Bayer frames are repaired by phase-aware correction (2x2 CFA split)
- interpolated color cines can be repaired channel-wise if needed
- mono cines use standard 8-neighbor repair

`red_pixels`, `green_pixels`, and `blue_pixels` are populated from the raw CFA
sensor mosaic for color cines. They are not taken from the debayered RGB image;
non-matching color sites are `NaN`.

`mode_frames` options:

- `method`: `"auto" | "mad" | "topk"`
- `q_bg`: bright baseline quantile (default `0.80`)
- `k_sigma`: MAD rejection scale for `method="mad"` (default `2.5`)
- `min_keep`: minimum accepted samples (default `3`)
- `max_keep`: cap for top-k memory in `method="topk"` (default `96`)
- `stack_limit`: `auto` threshold for choosing `mad` vs `topk` (default `128`)

## Packed 10-bit Decode

The package automatically selects:

1. Bundled native unpack library for your OS/arch.
1. NumPy fallback with the same lookup-table mapping as the C implementation.

Force fallback mode:

```bash
export CINE_READER_DISABLE_C_UNPACK=1
```

## Examples

- `python/examples/basic_usage.py`
- `python/examples/trim_and_background.py`

## Tests

Run:

```bash
PYTHONPATH=python/src pytest python/tests -q
```

The smoke test auto-skips if no sample `.cine` file is present.

Detailed API notes are in `python/API.md`.
