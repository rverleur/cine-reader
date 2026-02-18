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
cine = Cine(cine_path)
print(cine.FileHeader.ImageCount)
print(cine.ImageHeader.biWidth, cine.ImageHeader.biHeight)

cine.LoadFrame(cine.FileHeader.FirstImageNo)
img = cine.PixelArray

avg = cine.AverageFrames(cine.FileHeader.FirstImageNo, cine.FileHeader.FirstImageNo + 10)
bg = cine.ModeFrames(cine.FileHeader.FirstImageNo, cine.FileHeader.FirstImageNo + 20, method="auto")
rgb = cine.GetFrameRGB()

cine.CloseFile()
```

## Main API

`Cine` class supports both legacy and snake_case methods:
- `OpenCineFile` / `open_cine_file`
- `LoadFrame` / `load_frame`
- `NextFrame` / `next_frame`
- `CloseFile` / `close_file`
- `ReplaceDeadPixels` / `replace_dead_pixels`
- `AverageFrames` / `average_frames`
- `ModeFrames` / `mode_frames`
- `SaveFramesToNewFile` / `save_frames_to_new_file`
- `LoadFramesBatch` / `load_frames_batch`
- `GetFrameRGB`

Public parsed objects:
- `FileHeader`
- `ImageHeader`
- `CameraSetup`
- `ImageLocations`
- `PixelArray`

## Module Layout

The Python implementation is split into focused modules:
- `python/src/cine_reader/cine.py`: public `Cine` facade and file lifecycle.
- `python/src/cine_reader/frame_decode.py`: payload decode logic (8/16/24/48 and packed 10-bit).
- `python/src/cine_reader/image_ops.py`: dead-pixel replacement and Bayer demosaic utilities.
- `python/src/cine_reader/stats.py`: fast frame statistics (`average` and robust background estimators).
- `python/src/cine_reader/unpack.py`: native-library loading plus NumPy 10-bit fallback.

## Performance Hints

For large frame ranges:
- Use `ModeFrames(..., method="topk")` for bounded-memory robust background estimation.
- Use `ModeFrames(..., method="mad")` when you want legacy quantile/MAD behavior on shorter ranges.
- Keep `replace=False` unless dead-pixel correction is required.
- If you do many operations, reuse the same `Cine` object instead of reopening files.

`ModeFrames` options:
- `method`: `"auto" | "mad" | "topk"`
- `q_bg`: bright baseline quantile (default `0.80`)
- `k_sigma`: MAD rejection scale for `method="mad"` (default `2.5`)
- `min_keep`: minimum accepted samples (default `3`)
- `max_keep`: cap for top-k memory in `method="topk"` (default `96`)
- `stack_limit`: `auto` threshold for choosing `mad` vs `topk` (default `128`)

## Packed 10-bit Decode

The package automatically selects:
1. Bundled native unpack library for your OS/arch.
2. NumPy fallback with the same lookup-table mapping as the C implementation.

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

The smoke test will auto-skip if no sample `.cine` file is present.

Detailed API notes are in `python/API.md`.
