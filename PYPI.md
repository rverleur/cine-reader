# cine-reader

`cine-reader` is a Python package for reading Vision Research Phantom `.cine`
files on macOS, Linux, and Windows.

The PyPI distribution contains only the Python package. The repository also
includes a separate MATLAB implementation that stays in GitHub:

- Repository: <https://github.com/rverleur/cine-reader>
- MATLAB implementation: <https://github.com/rverleur/cine-reader/tree/main/Matlab>
- Python examples: <https://github.com/rverleur/cine-reader/tree/main/python/examples>
- Python API notes: <https://github.com/rverleur/cine-reader/blob/main/python/API.md>

## Installation

Install from PyPI:

```bash
pip install cine-reader
```

Development install from GitHub:

```bash
pip install "git+https://github.com/rverleur/cine-reader.git"
```

Editable install from a local checkout:

```bash
pip install -e .[dev]
```

## What The Package Provides

- High-level `Cine` reader for file metadata, frame access, frame iteration,
  trimming, and simple processing.
- Packed 10-bit decode with bundled native helpers and a NumPy fallback.
- Dead-pixel repair helpers for mono, Bayer/CFA, and RGB image arrays.
- Bilinear Bayer demosaic for raw color sensor frames.
- Low-memory frame statistics helpers for averaging and robust background
  estimation.

## Quick Start

```python
from pathlib import Path

from cine_reader import Cine

cine_path = Path("my_capture.cine")

with Cine(cine_path) as cine:
    print("frames:", cine.total_frames)
    print("range:", cine.first_frame_number, cine.last_frame_number)
    print("frame rate:", cine.frame_rate)
    print("exposure (s):", cine.exposure_time_seconds)

    cine.load_frame(cine.first_frame_number)
    raw_frame = cine.frame

    rgb_frame = cine.get_frame_rgb()
    average = cine.average_frames(cine.first_frame_number, cine.first_frame_number + 9)
    background = cine.mode_frames(cine.first_frame_number, cine.first_frame_number + 19)
```

## Frame And Color Behavior

- Mono cines load as 2D arrays.
- Raw color CFA/Bayer cines load as 2D sensor mosaics by default.
- Interpolated 24-bit and 48-bit color payloads load as 3-channel arrays.
- Set `debayer=True` on `Cine(...)` or call `debayer_frame()` to convert raw CFA
  frames to RGB.
- Set `remove_dead_pixels=True` on `Cine(...)` or call `replace_dead_pixels()`
  to repair dead pixels.
- `red_pixels`, `green_pixels`, and `blue_pixels` expose raw CFA sensor samples
  for Bayer frames, using `NaN` at non-matching locations.

## The `Cine` Class

### Constructor

```python
Cine(
    filename,
    keep_annotations=True,
    remove_dead_pixels=False,
    debayer=False,
    dead_value=None,
    dead_is_threshold=True,
    bayer_pattern="auto",
)
```

- `filename`: path to a `.cine` file.
- `keep_annotations`: keep annotation block bytes in `annotation_data` and
  `annotation`.
- `remove_dead_pixels`: repair dead pixels on each `load_frame`.
- `debayer`: debayer raw CFA/Bayer frames on each `load_frame`.
- `dead_value`: optional dead-pixel marker or threshold. If omitted, the value
  is inferred from camera metadata.
- `dead_is_threshold`: when `True`, values greater than or equal to
  `dead_value` are treated as dead pixels.
- `bayer_pattern`: `"auto"`, `"RGGB"`, `"BGGR"`, `"GRBG"`, or `"GBRG"`.

### Reader Lifecycle

- `open_cine_file(filename)`: reopen a `.cine` file and parse the top-level
  metadata blocks.
- `close_file()`: close the active file handle.
- Context manager support: `with Cine(path) as cine: ...`

### Metadata And Aliases

These properties are the most useful entry points for file metadata:

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

The specification-aligned metadata objects are also available directly:

- `file_header` as `CineHeader`
- `image_header` as `BitmapHeader`
- `camera_setup` as `Setup`
- `image_locations` as `ImageOffsets`

### Frame Access

- `load_frame(image_no, convert_bgr_to_rgb=False)`
  - Loads a single frame by global frame number.
  - `convert_bgr_to_rgb=True` converts 3-channel payloads to RGB on load.
- `next_frame(increment=1, convert_bgr_to_rgb=False)`
  - Loads the next frame relative to `current_frame`.
  - Negative increments are allowed.
- `frame` and `image`
  - Aliases for the currently loaded NumPy array.
- `get_frame_rgb(image_no=None, bayer_pattern="auto")`
  - Returns the current frame, or a selected frame, as RGB.
  - Raw CFA/Bayer frames are demosaiced first.

Example:

```python
with Cine("capture.cine") as cine:
    cine.load_frame(cine.first_frame_number)
    raw = cine.frame
    rgb = cine.get_frame_rgb()
```

### Pixel Repair And Demosaic

- `replace_dead_pixels(dead_value=None, dead_is_threshold=True)`
  - Repairs dead pixels on the current frame.
  - Works for mono, raw Bayer/CFA, and RGB data.
- `debayer_frame(bayer_pattern="auto")`
  - Converts the current raw CFA/Bayer frame to RGB in place.

Example:

```python
with Cine("capture.cine") as cine:
    cine.load_frame(cine.first_frame_number)
    cine.replace_dead_pixels()
    cine.debayer_frame()
    rgb = cine.frame
```

### Multi-Frame Operations

- `average_frames(start_frame, end_frame, replace_dead_pixels=False, chunk_size=8)`
  - Computes a per-pixel average over an inclusive frame range.
- `mode_frames(start_frame, end_frame, replace_dead_pixels=False, method="auto", q_bg=0.80, k_sigma=2.5, min_keep=3, max_keep=96, stack_limit=128)`
  - Computes a robust bright-background estimate.
  - `method="mad"` uses a full-stack quantile/MAD estimator.
  - `method="topk"` uses a bounded-memory top-k estimator.
  - `method="auto"` chooses between them from the range length.
- `load_frames_batch(start_frame, count)`
  - Loads consecutive frames into one stacked array.
  - Output shape is `[H, W, N]` for mono/raw CFA and `[H, W, 3, N]` for color.
- `save_frames_to_new_file(output_filename, start_frame, end_frame)`
  - Writes a trimmed `.cine` file for an inclusive frame range.

Example:

```python
with Cine("capture.cine") as cine:
    first = cine.first_frame_number
    last = min(first + 49, cine.last_frame_number)

    avg = cine.average_frames(first, last, chunk_size=8)
    bg = cine.mode_frames(first, last, method="topk")
    batch = cine.load_frames_batch(first, 5)
    cine.save_frames_to_new_file("trimmed.cine", first, last)
```

## Standalone Helper Functions

### Packed 10-bit Decode

- `unpack_10bit_data(data)`
  - Decodes Phantom packed 10-bit payloads.
  - Uses a bundled native unpack helper when one is available.
  - Falls back to NumPy automatically.
- `unpack_10bit_numpy(data)`
  - Pure-NumPy packed 10-bit decoder.

To force the NumPy path:

```bash
export CINE_READER_DISABLE_C_UNPACK=1
```

### Dead-Pixel Repair

- `replace_dead_pixels(frame, dead_value=4095, dead_is_threshold=False, bayer_raw=False)`
  - Dispatches to the right repair strategy for mono, Bayer, or RGB input.
- `replace_dead_pixels_mono(frame, dead_value=4095, dead_is_threshold=False)`
  - Repairs dead pixels in a 2D mono frame from valid 8-neighbor values.
- `replace_dead_pixels_bayer(frame, dead_value=4095, dead_is_threshold=False)`
  - Repairs a 2D raw Bayer/CFA frame phase-by-phase before demosaic.
- `replace_dead_pixels_rgb(frame, dead_value=4095, dead_is_threshold=False)`
  - Repairs each color channel independently in a 3D image.

Example:

```python
from cine_reader import replace_dead_pixels_bayer

clean = replace_dead_pixels_bayer(raw_bayer_frame, dead_value=4095)
```

### Demosaic

- `demosaic_bilinear(frame, pattern="RGGB")`
  - Bilinear Bayer demosaic for raw CFA frames.
  - Supported patterns are `"RGGB"`, `"BGGR"`, `"GRBG"`, and `"GBRG"`.

Example:

```python
from cine_reader import demosaic_bilinear

rgb = demosaic_bilinear(raw_bayer_frame, pattern="RGGB")
```

### Frame Statistics

- `average_from_frame_iter(frames, out_dtype=None, chunk_size=8)`
  - Computes a per-pixel mean from an iterable of equally shaped frames.
  - Returns `(average_frame, frame_count)`.
- `robust_background_mad_stack(frames, q_bg=0.80, k_sigma=2.5, min_keep=3, out_dtype=np.uint16)`
  - Full-stack bright-background estimator based on quantile and MAD rejection.
- `robust_background_topk(frames, frame_count, q_bg=0.80, min_keep=3, max_keep=96, out_dtype=np.uint16)`
  - Bounded-memory bright-background estimator that keeps the top-k samples per
    pixel.

Example:

```python
from cine_reader import average_from_frame_iter, robust_background_topk

avg, count = average_from_frame_iter(frames, chunk_size=16)
bg = robust_background_topk(frames, frame_count=count, q_bg=0.80)
```

## Metadata Classes

These classes are returned by the reader for direct access to CINE metadata:

- `CineHeader`
  - File header fields such as `FirstImageNo`, `ImageCount`, and
    `OffImageOffsets`.
- `BitmapHeader`
  - Image header fields such as `biWidth`, `biHeight`, and `biBitCount`.
- `ImageOffsets`
  - Frame byte-offset table as `pImage`.
- `Setup`
  - Camera setup metadata including frame rate, exposure, bit depth, color
    flags, and descriptive strings.

Example:

```python
with Cine("capture.cine") as cine:
    print(cine.file_header.FirstImageNo)
    print(cine.image_header.biWidth, cine.image_header.biHeight)
    print(cine.camera_setup.FrameRate, cine.camera_setup.RealBPP)
```

## Included Native Helpers

The wheel ships with runtime unpack libraries for packed 10-bit payloads:

- `unpack_data_win32.dll`
- `unpack_data_win64.dll`
- `unpack_data_elf64.so`
- `unpack_data_arm64.dylib`

If no matching helper can be loaded, `cine-reader` falls back to the NumPy
decoder automatically.

## MATLAB Implementation

The PyPI package is intentionally Python-only. If you also need the MATLAB
reader, use the same GitHub repository:

- MATLAB package entry point:
  <https://github.com/rverleur/cine-reader/blob/main/Matlab/Cine.m>
- MATLAB setup and examples:
  <https://github.com/rverleur/cine-reader/blob/main/Matlab/README.md>

## More Examples

- Basic usage:
  <https://github.com/rverleur/cine-reader/blob/main/python/examples/basic_usage.py>
- Trimming and background estimation:
  <https://github.com/rverleur/cine-reader/blob/main/python/examples/trim_and_background.py>
- Performance test:
  <https://github.com/rverleur/cine-reader/blob/main/python/examples/performance_test.py>
