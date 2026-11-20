# MATLAB API

Install the prebuilt backend once per checkout/update with
`addpath('<repo>/Matlab'); install_cine_backend`. Ordinary use needs MATLAB only;
developer builds are explicitly requested with `build_cine_backend`. See
[installation, compatibility and examples](README.md).

## Reader

The reader's existing call signatures remain available:

- `Cine(filename, 'RemoveDeadPixels', false, 'Debayer', false, 'DeadValue', [], 'BayerPattern', 'auto')`
- `OpenCineFile(filename)`, `CloseFile()`, `LoadFrame(frame_no)`, `NextFrame(increment)`
- `ReplaceDeadPixels(dead_value)`, `DebayerFrame(bayer_pattern)`, `GetFrameRGB(frame_no, bayer_pattern)`
- `AverageFrames(start_frame, end_frame, replace, chunk_size)`
- `ModeFrames(start_frame, end_frame, replace, 'method', 'auto', 'q_bg', .8, 'k_sigma', 2.5, 'min_keep', 3, 'max_keep', 96, 'stack_limit', 128)`
- `LoadFramesBatch(start_frame, count)`
- `SaveFramesToNewFile(output_filename, start_frame, end_frame)`

Frame ranges are inclusive and use the file's global frame numbers, which may
be negative. `LoadFramesBatch` explicitly allocates the requested batch;
ordinary reads retain only the current frame. `chunk_size` is validated and
retained for compatibility; the Rust mean accumulator streams frames directly.
`NextFrame` defaults to increment 1. Out-of-range reads raise an error.

`PixelArray` and `RawPixelArray` use the historical storage row orientation:
positive `ImageHeader.biHeight` means bottom-up. Interpolated color frames have
BGR channels; `GetFrameRGB` changes these to RGB or demosaics a raw Bayer image,
retaining row orientation. `DebayerFrame` changes `PixelArray` to RGB while
`RawPixelArray` keeps the decoded input. For top-down presentation or passing a
read frame to `CineWriter`, flip the rows when `biHeight > 0`, and convert BGR
to RGB if needed. Packed10 decoding returns linearized uint16 values, not raw
10-bit packed codes.

`LoadFramesBatch` returns H-by-W-by-count for mono/raw Bayer and
H-by-W-by-3-by-count for color (MATLAB can omit trailing singleton dimensions).
Returned arrays survive subsequent loads and closing the reader.

Constructor processing options are case-insensitive name/value pairs:

| Option | Default | Meaning |
| --- | --- | --- |
| `RemoveDeadPixels` | false | Repair matching marker values on each read |
| `DeadValue` | [] | Default marker 4095; specify the actual marker for your data |
| `Debayer` | false | Demosaic raw CFA data on each read |
| `BayerPattern` | `'auto'` | Infer CFA from metadata, or use RGGB/BGGR/GRBG/GBRG |

One-off repair and demosaicing mutate the current `PixelArray`. Raw CFA repair
uses same-color neighbors. Demosaicing is bilinear and applies no white balance,
gamma correction or tone mapping. `RedPixels`, `GreenPixels` and `BluePixels`
contain sensor samples with NaN at other color sites, rather than interpolated
full-color planes.

`AverageFrames` returns the integer-rounded mean in the current frame type.
`ModeFrames` returns a uint16 robust bright-background estimate for mono/raw
Bayer frames. `method='auto'` selects MAD for short ranges (`stack_limit`) and
top-k for longer ranges; MAD stores the selected frame stack, while top-k bounds
retained samples using `max_keep`. `q_bg` sets the bright-background quantile,
`k_sigma` controls MAD rejection, and `min_keep` controls the minimum samples.
This is not an exact histogram mode. The `replace` argument enables dead-pixel
repair for the statistic without changing the constructor configuration.

`SaveFramesToNewFile` copies the selected encoded frames without quantizing or
re-encoding them, retaining global frame numbers and slicing timestamp tags.
The destination must not exist.

`FileHeader`, `ImageHeader`, `CameraSetup`, `CurrentFrame`, `PixelArray`,
`RawPixelArray`, `ImageLocations`, `AnnotationSize`, `AnnotationData`,
`Annotation`, `ImageSize`, `RedPixels`, `GreenPixels` and `BluePixels` retain
their public names. Initial image state and the offsets vector are lazy.
`CameraSetup` materializes its legacy `SetupData` bytes, including tagged blocks,
on first access. Internal frame reading uses the cached fixed setup metadata.
Rust preserves/subsets tagged blocks as appropriate when trimming.
Explicit `CloseFile` materializes deferred initial image and metadata state so
these public properties remain available after closing. Deleting or reopening
an object releases the discarded state without materializing it.

Set `KeepAnnotations=true` before reading a frame to retain its annotation
bytes. `UseMemMap`, `AssumeConstAnn` and `Debug` remain compatibility properties;
the Rust backend controls I/O and validates bounds independently of them.

## Streaming writer

`CineWriter(filename, width, height, name, value, ...)` accepts:

| Option | Default | Meaning |
|---|---|---|
| `Channels` | 1 | 1 mono/Bayer or 3 RGB |
| `BitDepth` | 8 | uint8 at 8, uint16 at 9–16 |
| `Packed10` | false | Phantom packed10 gamma encoding, linear12 input |
| `FrameCount` | 0 | Known count; 0 means unknown-length stream |
| `FirstFrame` | 0 | First global frame number |
| `CFA` | 0 | Raw Bayer CFA identifier; 0 for mono/RGB |
| `FrameRate` | 30 | Positive frames per second |

Frames have top-down rows, with size H-by-W for mono/Bayer or H-by-W-by-3 for
RGB. Normal formats preserve samples exactly within the selected bit depth.
For Bayer data use `Channels=1` and the matching `CFA`: 3=GBRG, 4=RGGB, 5=GRBG,
6=BGGR (legacy identifiers 1=GBRG and 2=BGGR are also accepted).

With `Packed10=true`, the output depth is 12. uint8 input is scaled to linear12;
RGB input is sampled into the chosen Bayer CFA (RGGB by default). This is lossy.
uint16 packed10 inputs must be in [0,4095]; samples are quantized to the nearest
entry in the Phantom linearization table. This does not preserve arbitrary
16-bit values, and RGB-to-Bayer sampling discards two channels per site.
`WriteFrame(frame)` appends one frame, `Close()` finalizes and publishes,
`Abort()` discards unfinished output. `FramesWritten` counts successful writes.
The destructor aborts unfinished output; explicitly close successful writes.
An incorrect known `FrameCount` prevents successful finalization. Use
`FrameCount=0` for unknown lengths: the writer uses a temporary disk spool and
one final streaming copy, not a full in-memory video. Existing destinations are
protected. Use `onCleanup(@() delete(writer))` to abort if a loop errors.

## Image and video conversion

`write_cine(filename, frames, name, value, ...)` accepts a cell array of arrays
or image paths, a string array of image paths, or a MATLAB `VideoReader`.
Options are forwarded to `CineWriter`; dimensions/channels/type are inferred
from the first frame and VideoReader's frame rate is used by default.
Supply image paths in the desired temporal order; paths are loaded one at a
time. Indexed images are converted to RGB. Arbitrary format changes between
frames are rejected. Video format support is determined by MATLAB's installed
codecs, and video conversion consumes the `VideoReader` from its current
position. Variable source timing is represented using the chosen constant
`FrameRate`; per-frame acquisition timestamps are not recovered from video.

## Installation and validation

- `install_cine_backend`: verify and copy the matching collected Rust library
  and MEX gateway; uses the OS-provided SHA256 utility, no compiler tools.
- `build_cine_backend`: compile the Rust library and C gateway with the local
  developer toolchain. `build_mex_unpack10bit_cached` is its compatibility alias.
- `test_rust_backend(corpus_directory)`: synthetic reader/writer and media tests;
  optionally test first/middle/last frames of all camera CINEs in a directory.
- `test_prebuilt_backend`: validate current collected artifacts and exercise
  rejection of stale sources, corrupt/missing binaries and wrong ABI metadata.

The collected gateways' tested MATLAB releases and platform requirements are
listed in [README.md](README.md). MATLAB/CINE examples are under
[examples/](examples/); none require Image Processing or Statistics Toolbox.
