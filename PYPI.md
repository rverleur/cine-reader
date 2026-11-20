# cine-handler

`cine-handler` provides the `cine_reader` Python API for Vision Research Phantom
CINE files. A portable Rust backend handles file I/O, decoding, encoding, pixel
processing and statistics. NumPy supplies the Python array interface.

## Installation

Install a wheel matching your operating system and processor:

```sh
python -m pip install --only-binary=:all: cine-handler
```

Matching wheels include the native library. GitHub checkouts and source archives
use a verified prebuilt library for the current operating system and processor.
Normal installation never invokes Rust or a compiler. If no compatible binary
is available, installation stops with an explanation instead of starting a build.
See the
[build guide](https://github.com/rverleur/cine-reader/blob/main/docs/BUILDING.md)
for source, macOS, Linux and Windows builds.

## Read frames

```python
from cine_reader import Cine

with Cine("capture.cine") as cine:
    print(cine.total_frames, cine.frame_rate)
    cine.load_frame(cine.first_frame_number)
    frame = cine.image
    cine.next_frame()
```

Opening reads bounded metadata. Frames decode on demand. Existing API names,
frame numbering, dtypes, storage row order and BGR channel order are preserved.
Use `canonical=True` for top-down RGB arrays. Raw color CFA frames remain 2D
unless `debayer=True`; `remove_dead_pixels=True` enables pixel repair.

## Write images or video

```python
from cine_reader import write_cine, write_cine_from_images, write_cine_from_video

write_cine("images.cine", frames, frame_rate=1000)
write_cine("packed.cine", frames, encoding="packed10", frame_rate=1000)
write_cine_from_images("photos.cine", ["001.png", "002.png"], frame_rate=30)
write_cine_from_video("video.cine", "input.mp4")
```

`frames` can be a sequence, NumPy stack or generator of uint8/uint16 arrays.
`CineWriter` provides incremental writing. Normal encoding preserves mono/RGB
samples exactly. Packed10 quantizes linear12 samples with Phantom's nonlinear
lookup table; uint8 is scaled and RGB is sampled into a Bayer mosaic. Use normal
RGB for exact color preservation. Writers consume top-down RGB coordinates;
read back with `Cine(path, canonical=True)` for matching coordinates.

Known frame counts write directly. Unknown counts spool to disk and make one
final copy, keeping RAM bounded. Existing outputs are never overwritten.
Image-file decoding requires optional Pillow (`pip install 'cine-handler[images]'`).
Video decoding uses optional PyAV (`pip install 'cine-handler[video]'`), whose
wheels bundle the FFmpeg libraries. Install `cine-handler[media]` for both image
and video input. No separate media-tool installation is required by these APIs.

## Processing and formats

- Reads CINE v0/v1, normal8/16/24/48, packed10 and packed12, mono and raw CFA.
- Trims existing files without decoding and preserves relevant metadata.
- Repairs dead pixels, demosaics Bayer frames, averages frames and estimates
  robust backgrounds through Rust.
- Mean uses one accumulator; top-k retains a bounded sample set. Explicit MAD
  and batch-loading operations intentionally hold a stack.
- Uses baseline CPU instructions with no GPU or high-performance CPU requirement.

Proprietary compressed CCI needs the vendor SDK. Generated files follow the
supplied CINE reference and have FFmpeg interoperability coverage; direct PCC
validation remains a separate Windows check.

The [repository](https://github.com/rverleur/cine-reader) also includes a MATLAB
interface to the same backend and a standalone Rust library/CLI. MATLAB is not
included in the Python wheel. See the
[Python API](https://github.com/rverleur/cine-reader/blob/main/python/API.md) and
[MATLAB guide](https://github.com/rverleur/cine-reader/blob/main/Matlab/README.md).
