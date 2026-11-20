# cine-reader

Read, process, trim and write Vision Research Phantom `.cine` files with Python,
MATLAB or a standalone Rust library/tool. One Rust backend handles file I/O,
encoding, decoding and pixel processing. Frames load on demand, keeping memory overhead low.

The Python distribution is **`cine-handler`**; its import name is **`cine_reader`**.
See the [0.2.0 changes](CHANGELOG.md), [Python API](python/API.md),
[MATLAB API](Matlab/API.md) and [validation results](docs/VALIDATION.md).

## Measured performance

Measured on **Apple M4 Max, 16 CPU cores, 128 GiB RAM, macOS 26.6.2**, using
the published **cine-handler 0.2.0** macOS wheel, Python 3.14.6, NumPy 2.5.5 and
Pillow 13.0.0 on November 19, 2026. The benchmark streamed the first **100 frames
from each of six camera recordings**, using local APFS storage, without a GPU
or an explicit worker pool.

All values below are **milliseconds per frame per megapixel (ms/frame/MPx)**; lower
is faster. Normalize as `elapsed_milliseconds / (frame_count * width * height / 1e6)`.
RGB uses spatial megapixels, without multiplying by its three channels.

**Reading:** five sequential passes after an initial traversal, with 1,500
individual frame measurements per row. Timing covers `load_frame()` and access
to the resulting NumPy array, excluding file construction and TIFF saving.
The color RGB row also includes bilinear demosaicing; the color raw row retains
the Bayer sensor mosaic.

| Reading operation | Mean | Median | 95th percentile |
| --- | ---: | ---: | ---: |
| Monochrome, normal 12-bit / packed10 | 0.262 | 0.305 | 0.325 |
| Color, packed10 → raw Bayer | 0.337 | 0.330 | 0.399 |
| Color, packed10 → RGB | 3.131 | 3.130 | 3.272 |

**Writing:** five complete 100-frame conversions per recording, using ordered,
uncompressed TIFF files and a known frame count. These are end-to-end
`write_cine_from_images()` timings: TIFF opening/decoding, encoding, headers,
file synchronization and finalization are included. TIFF export and subsequent
verification are excluded. Each row pools 15 whole-file trials normalized by
frame count and megapixels, with equal numbers of trials per recording.

| TIFF input → CINE output | Mean | Median | Minimum–maximum |
| --- | ---: | ---: | ---: |
| Monochrome uint16 → packed10 | 7.072 | 6.601 | 6.261–9.403 |
| Monochrome uint16 → normal 12-bit | 8.839 | 6.151 | 5.853–14.964 |
| Color Bayer uint16 → packed10 | 9.949 | 9.281 | 8.614–12.006 |
| Color Bayer uint16 → normal 12-bit Bayer | 14.468 | 14.682 | 11.374–17.457 |
| Color RGB uint8 → packed10 Bayer | 2.917 | 2.966 | 2.746–3.093 |

For a concrete example, `visible_0_2500.cine` has 1280 × 256 pixels per frame.
Its median raw frame load took **0.116 ms**, or **1.018 ms** including RGB
demosaicing. Writing 100 frames from raw uint16 TIFFs to packed10 took a median
**0.290 s**; writing from RGB8 TIFFs took **0.098 s**. The RGB8 route is lossy:
it reduces the original linear 12-bit samples to 8-bit RGB, then samples a Bayer
mosaic and applies packed10 quantization.

<details>
<summary>Per-recording median timings</summary>

All timing columns use ms/frame/MPx. Writing columns use the original uint16
sensor TIFFs. Read statistics pool individual normalized frames, with equal
numbers of frames and passes per recording; monochrome results therefore
combine both normal and packed10 input.

| Recording | Source format | Dimensions | Raw reading | Packed10 writing | Normal writing |
| --- | --- | --- | ---: | ---: | ---: |
| `visible_0_2500.cine` | Packed10 color Bayer | 1280 × 256 | 0.354 | 8.843 | 14.682 |
| `Color23CT.cine` | Packed10 color Bayer | 1280 × 384 | 0.323 | 11.927 | 11.961 |
| `shot.cine` | Packed10 color Bayer | 1280 × 256 | 0.330 | 9.100 | 17.218 |
| `45Degree 2.cine` | Normal 12-bit mono | 512 × 384 | 0.160 | 7.918 | 14.380 |
| `FeNe_knife.cine` | Packed10 mono | 1280 × 800 | 0.311 | 6.412 | 6.128 |
| `H50 15.cine` | Packed10 mono | 1280 × 800 | 0.308 | 6.601 | 5.949 |

</details>

Every frame of every generated trial was reopened and checked. All five
packed10 sources preserved their decoded sensor samples exactly through
uint16 TIFF → packed10, including the color CFA. The normal 12-bit source
matched the expected packed10 quantization, with maximum error **4 / 4095**;
normal outputs preserved all input samples exactly. Frame rate, acquisition
start number and CFA were retained; other camera metadata was regenerated.

## Install for Python

For the published 0.2.0 release:

```sh
python -m pip install --only-binary=:all: "cine-handler[media]==0.2.0"
```

For a downloaded or cloned copy of this repository, run from its root:

```sh
python -m pip install ".[media]"
# Editable installation for IDE use:
python -m pip install -e ".[media]"
```

Omit `[media]` if you only need CINE files and NumPy arrays.
The `images` extra installs Pillow; `video`
installs PyAV; `media` installs both. PyAV wheels include the FFmpeg libraries, so
the default video conversion needs no separate FFmpeg executable.

Wheels include their matching Rust library. Checkouts and source archives select
it from `binaries/`, validating its architecture, checksums and Rust source
fingerprint. **Python users do not need Rust, a C compiler or MATLAB.** Missing or
incompatible binaries produce an error rather than starting a compiler download.
Use a 64-bit Python 3.9 or newer; Python dependencies can impose their own OS
minimums. If the older `cine-reader` distribution is installed, uninstall it
first because it shares the `cine_reader` import name.

| Included target | Python backend | MATLAB gateway tested with |
| --- | --- | --- |
| Apple Silicon macOS | ARM64, macOS 11+ | MATLAB R2025b |
| Windows | x64 | MATLAB R2026b |
| Linux | x64, glibc 2.28+ | MATLAB R2026b on Debian 13 |

Intel macOS, Windows ARM64, Linux ARM64 and musl/Alpine Linux need separate
builds. MATLAB also has its own OS requirements; its Linux gateway imports glibc
symbols through 2.34. See [binary coverage](binaries/README.md) for exact provenance.

## Read and write in Python

```python
from cine_reader import Cine

with Cine("capture.cine", canonical=True) as cine:
    print(cine.total_frames, cine.frame_rate)
    for number in range(cine.first_frame_number, cine.last_frame_number + 1):
        cine.load_frame(number)
        frame = cine.image
        # Process this frame before requesting the next one.
```

`canonical=True` returns top-down coordinates and RGB channels for decoded color
images. The default preserves the previous API's storage row order and BGR
convention. Raw Bayer frames remain 2D mosaics unless `debayer=True`. Frame
numbers follow the acquisition numbering, which can be negative.

```python
import numpy as np
from cine_reader import CineWriter, write_cine_from_images, write_cine_from_video

with CineWriter("generated.cine", width=640, height=480, frame_rate=1000, frame_count=10) as writer:
    for number in range(10):
        writer.write_frame(np.full((480, 640), number, dtype=np.uint16))

write_cine_from_images("photos.cine", ["001.png", "002.png"], frame_rate=30)
write_cine_from_video("video.cine", "input.mp4", encoding="packed10")
```

Use `encoding="normal"` for lossless uint8/uint16 mono or RGB; `packed10` uses
Phantom's nonlinear quantization. Packed10 uint16 input must be in `0..4095`,
while uint8 is scaled to that range. RGB packed10 input is sampled into a Bayer
mosaic, so normal RGB is preferable when preserving every color sample matters.
Packed12 reading is also supported. Proprietary compressed `.cci` is unsupported.

Writers accept one frame at a time. A known count writes directly; an unknown
count uses a disk spool and final copy. Existing destinations are never replaced.
Mean uses one accumulator and top-k backgrounds retain a bounded set of samples;
explicit MAD and batch APIs intentionally allocate a frame stack.

The [Python examples](python/examples/README.md) cover reading, metadata, color,
repair, statistics, trimming, incremental writing, image lists, video input and
performance measurement. Configure their `__main__` blocks in your IDE.

## Install and use with MATLAB

Download or clone this repository, then run in MATLAB from its root:

```matlab
addpath(fullfile(pwd, 'Matlab'));
install_cine_backend;

cine = Cine('capture.cine');
cine.LoadFrame(cine.FileHeader.FirstImageNo);
image = cine.PixelArray;
cine.CloseFile();
```

The installer copies the matching verified MEX gateway and Rust library from
`binaries/`. **MATLAB users need MATLAB, but no Python, Rust or C compiler.** Keep
`Matlab/` on the MATLAB path for later sessions. The MATLAB interface offers
`Cine`, `CineWriter` and `write_cine`; the small C gateway only marshals arrays
and calls Rust. It is still required and is not a leftover C implementation.

See the [MATLAB installation guide](Matlab/README.md),
[API](Matlab/API.md) and [examples](Matlab/examples/README.md). MATLAB video input
uses `VideoReader`; codec availability depends on the MATLAB installation and OS.

## Standalone tool and Rust development

The collected `cine-tool` runs without Python or MATLAB. For example on Linux:

```sh
binaries/x86_64-unknown-linux-gnu/cine-tool info capture.cine
binaries/x86_64-unknown-linux-gnu/cine-tool verify capture.cine
binaries/x86_64-unknown-linux-gnu/cine-tool extract capture.cine 0 first-frame.raw
binaries/x86_64-unknown-linux-gnu/cine-tool transcode capture.cine converted.cine normal
```

Use the matching target folder on macOS or Windows (`cine-tool.exe` on Windows).
CLI indexes are zero based; extracted samples are tightly packed, top-down RGB
or mono, with little-endian uint16 values. Rust users can use `Reader`,
`writer::CineWriter` and processing APIs directly; see the [Rust guide](rust/cine-core/README.md).

Developers modifying Rust need Rust/Cargo and a platform linker. Follow
[BUILDING.md](docs/BUILDING.md) for OS-specific setup, rebuilding, MATLAB linking
and binary collection. Install the [commit checks](docs/DEVELOPMENT.md) in every
development clone. The [release guide](docs/RELEASING.md) describes packaging the
collected binaries into wheels and source archives without rebuilding Rust.

## Format validation and license

The implementation follows `docs/reference/Cine File Format.pdf`. Tests cover
camera recordings, synthetic format variants, malformed files, processing and
writer round trips, with independent FFmpeg checks. **Direct PCC opening/playback
has not been verified**; see [validation limits](docs/VALIDATION.md).

Project code is licensed under [MIT](LICENSE). The third-party CINE format PDF
retains its original copyright and is not covered by the project license.
