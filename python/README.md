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
bg = cine.ModeFrames(cine.FileHeader.FirstImageNo, cine.FileHeader.FirstImageNo + 20)
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
