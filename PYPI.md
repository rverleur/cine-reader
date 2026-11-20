# cine-handler

Read, process, trim and write Vision Research Phantom `.cine` files from Python.
A portable Rust backend handles I/O, decoding, encoding and pixel processing;
NumPy supplies the array interface. Frames load on demand, with no GPU or
special CPU instruction set required.

**Package name:** `cine-handler` · **Python import:** `cine_reader`

## Installation

```sh
python -m pip install --only-binary=:all: cine-handler
# Include image-file and video conversion:
python -m pip install --only-binary=:all: "cine-handler[media]"
```

Wheels include the native library. No Rust, C compiler or MATLAB installation
is needed. Version 0.2.0 supplies Apple Silicon macOS (ARM64, macOS 11+), Windows
x64 and Linux x64/glibc 2.28+ backends. Use 64-bit Python 3.9 or newer; dependency
wheels may require newer OS versions. Intel macOS, Windows ARM64, Linux ARM64 and
musl/Alpine are not included targets.

A downloaded/cloned GitHub checkout or source archive also installs without
compilers because it contains the same verified backends:

```sh
python -m pip install ".[media]"
# For working directly in an IDE checkout:
python -m pip install -e ".[media]"
```

`images` installs Pillow, `video` installs PyAV, and `media` installs both. PyAV
wheels bundle FFmpeg libraries, so ordinary video conversion needs no separate
`ffmpeg` or `ffprobe` executable. If you have the older `cine-reader` distribution,
uninstall it first: it shares the `cine_reader` import name.

## Read frames

```python
from cine_reader import Cine

with Cine("capture.cine", canonical=True) as cine:
    print(cine.total_frames, cine.frame_rate)
    for number in range(cine.first_frame_number, cine.last_frame_number + 1):
        cine.load_frame(number)
        frame = cine.image
        # Analyze one frame at a time.
```

Opening reads bounded metadata. Pixels, offsets and raw payloads load when
requested. Acquisition frame numbers can be negative. `canonical=True` gives
top-down coordinates and RGB channel order; the default retains the previous
reader's storage row order and BGR convention. Raw CFA/Bayer frames remain 2D
unless `debayer=True`; `remove_dead_pixels=True` enables pixel repair.

## Write arrays, images and video

```python
import numpy as np
from cine_reader import write_cine, write_cine_from_images, write_cine_from_video

frames = [np.full((64, 96), value, dtype=np.uint16) for value in (0, 100, 200)]
write_cine("normal.cine", frames, frame_rate=1000)
write_cine("packed.cine", frames, encoding="packed10", frame_rate=1000)
write_cine_from_images("photos.cine", ["001.png", "002.png"], frame_rate=30)
write_cine_from_video("video.cine", "input.mp4")
```

`write_cine` accepts sequences, frame-first NumPy stacks or generators;
`CineWriter` provides incremental writing. Normal encoding preserves uint8/uint16
mono and RGB samples. Packed10 quantizes linear12 values with Phantom's nonlinear
lookup table: uint16 input must be in `0..4095`, uint8 is scaled, and RGB is sampled
into a Bayer mosaic. Use normal RGB to preserve every input color sample.
Writers consume top-down RGB coordinates; read back with `canonical=True`.

Known counts write directly. Unknown counts spool to disk and make one final
copy, keeping RAM bounded. Existing destinations are never overwritten.

## Processing and formats

- Reads CINE v0/v1, normal8/16/24/48, packed10 and packed12, mono and raw CFA.
- Trims encoded frames without decoding, preserving relevant metadata.
- Repairs dead pixels, demosaics Bayer frames, averages recordings and estimates
  robust backgrounds through Rust.
- Mean uses one accumulator; top-k retains bounded samples. Explicit MAD and
  batch loading intentionally hold a stack.

Proprietary compressed CCI is unsupported. Generated files follow the CINE
format reference and pass independent FFmpeg checks. Direct PCC opening/playback
has not yet been verified.

## Documentation and examples

- [Python installation and usage](https://github.com/rverleur/cine-reader/blob/v0.2.0/python/README.md)
- [Python API](https://github.com/rverleur/cine-reader/blob/v0.2.0/python/API.md)
- [Runnable Python examples](https://github.com/rverleur/cine-reader/tree/v0.2.0/python/examples)
- [Developer setup and native builds](https://github.com/rverleur/cine-reader/blob/v0.2.0/docs/BUILDING.md)
- [Validation results and limitations](https://github.com/rverleur/cine-reader/blob/v0.2.0/docs/VALIDATION.md)
- [Changes in 0.2.0](https://github.com/rverleur/cine-reader/blob/v0.2.0/CHANGELOG.md)

The [repository](https://github.com/rverleur/cine-reader) also supplies a MATLAB
interface and standalone Rust library/CLI. Python wheels contain only the Python
interface and its matching native library. MATLAB users install the checkout's
prebuilt gateway with `install_cine_backend`; see the
[MATLAB guide](https://github.com/rverleur/cine-reader/blob/v0.2.0/Matlab/README.md).

Project code is MIT licensed. This package is an independent implementation and
does not require Vision Research software for its supported formats.
