# Python API Notes

## Cine Class Lifecycle

```python
from cine_reader import Cine

with Cine("sample_data/TrimmedCine.cine") as cine:
    cine.LoadFrame(cine.FileHeader.FirstImageNo)
    frame = cine.PixelArray
```

- `OpenCineFile(path)`: open/parse file headers and preload first frame.
- `LoadFrame(frame_no, convert_bgr_to_rgb=False)`: decode one frame payload.
- `CloseFile()`: close handle.

## Frame Access

- `PixelArray`: latest decoded frame.
- `LoadFramesBatch(start_frame, count)`: stacked output on last axis.
  - Mono: `[H, W, N]`
  - Color: `[H, W, 3, N]`

## Processing Methods

- `ReplaceDeadPixels(dead_value=4095)`: in-place mono dead-pixel correction.
- `GetFrameRGB(image_no=None, bayer_pattern="RGGB")`: RGB output from current frame.

## Statistics Methods

- `AverageFrames(start_frame, end_frame, replace=False)`
  - Chunked accumulation for lower memory.
- `ModeFrames(start_frame, end_frame, replace=False, method="auto", q_bg=0.80, k_sigma=2.5, min_keep=3, max_keep=96, stack_limit=128)`
  - `method="mad"`: legacy quantile/MAD robust estimator.
  - `method="topk"`: low-memory top-k bright estimator.
  - `method="auto"`: `mad` for short ranges, `topk` for long ranges.

## I/O Utilities

- `SaveFramesToNewFile(output_filename, start_frame, end_frame)`
  - Writes a trimmed `.cine` preserving headers/setup/offsets.

## Optional Functional Helpers

These are available directly from the package:

```python
from cine_reader import (
    unpack_10bit_data,
    unpack_10bit_numpy,
    replace_dead_pixels_mono,
    demosaic_bilinear,
    average_from_frame_iter,
    robust_background_mad_stack,
    robust_background_topk,
)
```
