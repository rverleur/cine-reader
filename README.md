# cine-reader

Streaming Vision Research Phantom CINE reading and writing, with one portable
Rust backend and compatible Python and MATLAB interfaces. The core has no
third-party dependencies and requires no GPU or optional CPU instruction set.

This is a **local, unreleased refactor**. Publishing workflows and the Python
package version are unchanged for the later release work. See the
[build instructions](docs/BUILDING.md) before installing this checkout.

## Python

The distribution is `cine-handler`; the import remains `cine_reader`. A source
installation needs Rust/Cargo and a linker. A matching platform wheel includes
the backend and needs no Rust installation at runtime.

```sh
python -m pip install -e .
```

Existing calls retain their names, arguments, frame numbering, NumPy dtypes,
storage row order and BGR convention:

```python
from cine_reader import Cine

with Cine("capture.cine") as cine:
    print(cine.total_frames, cine.frame_rate)
    cine.load_frame(cine.first_frame_number)
    image = cine.image
    cine.next_frame()
```

Opening reads bounded metadata only. The first frame, offset table, raw payload
bytes and color-sample arrays are materialized when requested. Returned NumPy
frames remain valid when subsequent frames load or the reader closes. Explicit
close materializes remaining legacy state so it stays available afterward;
destruction and reopening release discarded state without that extra work.

For ordinary top-down image coordinates and RGB channels, opt in with
`Cine(path, canonical=True)`. This is useful when reading newly encoded images:

```python
import numpy as np
from cine_reader import Cine, write_cine, write_cine_from_images, write_cine_from_video

images = [np.zeros((480, 640), dtype=np.uint16) for _ in range(3)]
write_cine("normal.cine", images, frame_rate=1000)
write_cine("packed.cine", images, encoding="packed10", frame_rate=1000)
write_cine_from_images("photos.cine", ["001.png", "002.png"], frame_rate=30)
write_cine_from_video("video.cine", "input.mp4")

with Cine("normal.cine", canonical=True) as cine:
    assert np.array_equal(cine.image, images[0])
```

`CineWriter` accepts one frame at a time; `write_cine` also accepts generators.
Known frame counts write in a single pass. Unknown counts use a disk spool and
one final copy, keeping memory independent of the number of frames. Existing
destinations are never overwritten, and unsuccessful writes are discarded.
Image decoding uses optional Pillow (`pip install '.[images]'`); video decoding
uses separately installed FFmpeg/FFprobe. Neither is needed for arrays or CINE
reading. See the [Python API](python/API.md).

## Encodings and orientation

| Encoding | Input/output |
| --- | --- |
| Normal | Lossless uint8/uint16 grayscale or RGB; CFA mosaics also supported |
| Packed10 | Phantom nonlinear 10-bit codes expanded to linear12 on read; quantized on write |
| Packed12 | Lossless packed12 reading |

Packed10 uint16 input must be in `0..4095`; uint8 is scaled to that range. RGB
input to packed10 is sampled into a Bayer mosaic, losing two color components
per pixel. Use normal RGB when exact color preservation matters. Quantization
chooses the nearest Phantom lookup-table value; arbitrary linear12 samples do
not round-trip exactly through packed10.

Normal frames use the manual's bottom-up BGR storage and positive height;
packed frames use top-down storage. Binding defaults preserve the old reader's
storage order. Canonical reading converts coordinates/channels without changing
the on-disk convention. Short final packed groups are zero padded.

The writer implements the supplied format reference, including SETUP, timestamps,
64-bit offsets and annotations. Outputs have also been checked independently with
FFmpeg. **PCC acceptance still requires a Windows/PCC check**; PCC is not available
in this environment. Proprietary compressed `.cci` files require the vendor SDK
and are rejected.

## MATLAB

```matlab
addpath('Matlab');
build_cine_backend;
cine = Cine('capture.cine');
cine.LoadFrame(cine.CurrentFrame + 1);
image = cine.PixelArray;
cine.CloseFile();
```

The new `cine_mex` gateway marshals MATLAB arrays into the same Rust library. It
contains no CINE parser, decoder or image-processing implementation. Existing
`Cine` methods remain available; `CineWriter` and `write_cine` add image/video
encoding. See [MATLAB setup and API](Matlab/README.md).

## Standalone Rust

```sh
cargo build --release --workspace --locked
target/release/cine-tool info capture.cine
target/release/cine-tool verify capture.cine
target/release/cine-tool extract capture.cine 0 first-frame.raw
target/release/cine-tool transcode capture.cine converted.cine normal
```

CLI indexes are zero based. Extracted bytes are tightly packed, top-down RGB or
monochrome; uint16 samples are little endian. `Reader`, `writer::CineWriter`,
image processing and statistics work independently of either binding. See
[Rust API examples](rust/cine-core/README.md).

## Building and verification

See [BUILDING.md](docs/BUILDING.md) for macOS, Linux and Windows builds, wheel
tagging, source installs and MATLAB relinking. Native macOS ARM64 binaries are
built here; build other architectures on their corresponding platforms.
Generated binaries stay local and are ignored by Git.

```sh
cargo test --workspace --locked
python -m pytest python/tests -q
```

[Validation notes](docs/VALIDATION.md) record corpus checks, independent comparisons,
performance measurements and remaining platform validation. No publishing, CI,
or commit-hook changes are included in this refactor.
