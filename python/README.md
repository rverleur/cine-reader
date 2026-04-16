# Python Package (`cine_reader`)

`cine_reader` reads Vision Research Phantom `.cine` files from Python.

Repository:

- `https://github.com/rverleur/cine-reader`

## Installation

There is currently no PyPI package. Install from a GitHub release, from Git,
or from a local checkout.

### Install from a GitHub release

Download the release wheel:

```text
cine_reader-X.Y.Z-py3-none-any.whl
```

Then install it with:

```bash
pip install cine_reader-X.Y.Z-py3-none-any.whl
```

Direct install from a release asset URL:

```bash
pip install "https://github.com/rverleur/cine-reader/releases/download/vX.Y.Z/cine_reader-X.Y.Z-py3-none-any.whl"
```

You can also install the source distribution:

```bash
pip install cine_reader-X.Y.Z.tar.gz
```

### Install the latest version from GitHub

```bash
pip install "git+https://github.com/rverleur/cine-reader.git"
```

### Install from a local checkout

```bash
pip install .
```

Editable install for development:

```bash
pip install -e .
```

## Quick Start

```python
from pathlib import Path
from cine_reader import Cine

cine_path = Path("sample_data/TrimmedCine.cine")

with Cine(
    cine_path,
    remove_dead_pixels=False,
    debayer=False,
) as cine:
    print(cine.total_frames)
    print(cine.first_frame_number, cine.last_frame_number)
    print(cine.frame_rate, cine.exposure_time_seconds)

    cine.load_frame(cine.first_frame_number)
    frame = cine.frame

    rgb = cine.get_frame_rgb()
    avg = cine.average_frames(cine.first_frame_number, cine.first_frame_number + 10)
    bg = cine.mode_frames(cine.first_frame_number, cine.first_frame_number + 20)
```

## Current Frame Behavior

Frame loading now follows the actual CINE data type:

- mono cines load as 2D arrays
- raw color CFA/Bayer cines load as 2D sensor mosaics by default
- interpolated 24-bit and 48-bit color payloads load as 3-channel arrays
- `debayer=True` debayers raw CFA/Bayer frames automatically on every
  `load_frame`
- `remove_dead_pixels=True` repairs pixels automatically on every `load_frame`

For raw color CFA/Bayer frames:

- `red_pixels`
- `green_pixels`
- `blue_pixels`

are `[H, W]` `float32` arrays with actual sensor samples at that color's
locations and `NaN` elsewhere. These are based on the raw sensor mosaic, not
the debayered RGB image.

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

Useful aliases:

- `first_frame_number`
- `total_frames`
- `last_frame_number`
- `frame_rate`
- `exposure_time_ns`
- `exposure_time_seconds`
- `exposure_time`
- `recording_datetime`
- `recording_date`
- `cfa_code`
- `bayer_pattern`
- `image`
- `frame`
- `red_pixels`
- `green_pixels`
- `blue_pixels`

## Packed 10-bit Decode

The package tries to use a bundled native unpack helper for packed 10-bit
payloads and falls back to NumPy when needed.

Bundled runtime files:

- `unpack_data_win32.dll`
- `unpack_data_win64.dll`
- `unpack_data_elf64.so`
- `unpack_data_arm64.dylib`

Force NumPy fallback:

```bash
export CINE_READER_DISABLE_C_UNPACK=1
```

## Batch Shapes

`load_frames_batch(start_frame, count)` returns:

- mono or raw CFA: `[H, W, N]`
- debayered or interpolated color: `[H, W, 3, N]`

## Performance Notes

- `python/examples/performance_test.py` measures frame-loading throughput into
  a preallocated output array.
- `average_frames(..., chunk_size=...)` trades memory for lower Python
  overhead.
- `mode_frames(..., method="topk")` gives bounded-memory robust background
  estimation for longer ranges.
- `mode_frames(..., method="mad")` uses quantile/MAD rejection on a full stack.
- Dead-pixel repair and debayering are optional because they add per-frame
  processing cost.

## Examples

- `python/examples/basic_usage.py`
- `python/examples/trim_and_background.py`
- `python/examples/performance_test.py`

## Tests

Run:

```bash
PYTHONPATH=python/src pytest python/tests -q
```

If `pytest` is not installed in your environment yet:

```bash
pip install pytest
```

The smoke test auto-skips if no local sample `.cine` file is present.

Detailed API notes are in `python/API.md`.
