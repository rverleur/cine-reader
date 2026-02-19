# Python API Notes

## Reader Lifecycle

```python
from cine_reader import Cine

with Cine("sample_data/TrimmedCine.cine") as cine:
    cine.load_frame(cine.first_frame_number)
    frame = cine.image
```

- `open_cine_file(filename)`
  - `filename`: path to `.cine`.
- `close_file()`
  - closes active file handle.

## Frame Access

- `load_frame(image_no, convert_bgr_to_rgb=False)`
  - `image_no`: global frame number (`file_header.FirstImageNo .. last_frame_number`).
  - `convert_bgr_to_rgb`: channel-order conversion for 3-channel payloads.
- `next_frame(increment=1, convert_bgr_to_rgb=False)`
  - `increment`: frame-number step (can be negative).
- `image` / `frame`
  - alias for latest decoded pixel array (`pixel_array`).
- `load_frames_batch(start_frame, count)`
  - `start_frame`: first frame number in range.
  - `count`: number of consecutive frames.
  - output shape:
    - mono: `[H, W, N]`
    - color: `[H, W, 3, N]`

## Image Processing

- `replace_dead_pixels(dead_value=4095)`
  - `dead_value`: marker value for dead sensor pixels.
- `get_frame_rgb(image_no=None, bayer_pattern="RGGB")`
  - `image_no`: optional frame number to load first.
  - `bayer_pattern`: one of `RGGB`, `BGGR`, `GRBG`, `GBRG`.

## Statistics

- `average_frames(start_frame, end_frame, replace_dead_pixels=False, chunk_size=8)`
  - `start_frame`, `end_frame`: inclusive frame range.
  - `replace_dead_pixels`: apply dead-pixel correction before averaging.
  - `chunk_size`: chunked accumulation size for bounded-memory averaging.
- `mode_frames(start_frame, end_frame, replace_dead_pixels=False, method="auto", q_bg=0.80, k_sigma=2.5, min_keep=3, max_keep=96, stack_limit=128)`
  - `method`: `auto | mad | topk`.
  - `q_bg`: bright-background quantile threshold.
  - `k_sigma`: MAD rejection multiplier (`mad` mode).
  - `min_keep`: minimum accepted samples per pixel.
  - `max_keep`: top-k cap (`topk` mode).
  - `stack_limit`: switch threshold for `auto`.

## File Utilities

- `save_frames_to_new_file(output_filename, start_frame, end_frame)`
  - `output_filename`: destination `.cine` path.
  - `start_frame`, `end_frame`: inclusive frame range to copy.

## Useful Top-Level Metadata Aliases

- `first_frame_number` -> `file_header.FirstImageNo`
- `total_frames` -> `file_header.ImageCount`
- `last_frame_number` -> derived
- `frame_rate` -> best available setup frame rate
- `exposure_time_ns` / `exposure_time_seconds` / `exposure_time`
- `recording_datetime` / `recording_date`

## Specification-Aligned Metadata Objects

Field names inside these objects intentionally follow CINE/BITMAP naming:

- `file_header` (`CineHeader`)
- `image_header` (`BitmapHeader`)
- `camera_setup` (`Setup`)
- `image_locations` (`ImageOffsets`)

Examples of spec-style fields:

- `file_header.FirstImageNo`
- `file_header.ImageCount`
- `image_header.biWidth`
- `image_header.biBitCount`
- `camera_setup.FrameRate`
- `camera_setup.ShutterNs`
- `camera_setup.RealBPP`
