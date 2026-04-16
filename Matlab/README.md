# MATLAB Reader

This folder contains the MATLAB implementation of the Phantom `.cine` reader.

Repository:

- `https://github.com/rverleur/cine-reader`

The public MATLAB entry point is:

- `Matlab/Cine.m`

## Installation and Setup

MATLAB support is not installed by the Python wheel. Use it directly from a
repository checkout or from a source archive downloaded from GitHub.

### 1. Get the repository

Clone the repo or download a release source archive from GitHub:

```text
https://github.com/rverleur/cine-reader
```

### 2. Add `Matlab/` to the MATLAB path

```matlab
addpath(genpath('<repo>/Matlab'))
```

### 3. Check packed 10-bit support

Runtime unpack libraries are expected under `Matlab/C_Files/`:

- `unpack_data_win32.dll`
- `unpack_data_win64.dll`
- `unpack_data_elf64.so`
- `unpack_data_arm64.dylib`

For packed 10-bit MATLAB decoding, you should also build
`private/mex_unpack10bit_cached` for your local MATLAB version and platform.

Build it from the MATLAB folder:

```matlab
cd('<repo>/Matlab')
build_mex_unpack10bit_cached
```

For standard unpacked 8-bit, 16-bit, 24-bit, and 48-bit payloads, the MEX file
is not needed.

## Quick Start

```matlab
cine = Cine(fullfile('<repo>', 'sample_data', 'TrimmedCine.cine'), ...
    'RemoveDeadPixels', false, 'Debayer', false);

first = cine.FileHeader.FirstImageNo;

cine.LoadFrame(first);
frame = cine.PixelArray;

avg = cine.AverageFrames(first, first + 10, false);
bg = cine.ModeFrames(first, first + 20, false, 'method', 'auto');
rgb = cine.GetFrameRGB(first, 'RGGB');
```

## Current Frame Behavior

The MATLAB reader matches the Python behavior:

- mono cines load as 2D arrays
- raw color CFA/Bayer cines load as 2D sensor mosaics by default
- interpolated color payloads load as 3-channel arrays
- `'Debayer', true` debayers raw CFA/Bayer frames on every `LoadFrame`
- `'RemoveDeadPixels', true` repairs pixels on every `LoadFrame`

For raw color CFA/Bayer frames:

- `RedPixels`
- `GreenPixels`
- `BluePixels`

are `[H x W]` `single` arrays with actual sensor samples at the matching color
sites and `NaN` elsewhere. These are taken from the raw sensor mosaic, not from
the debayered RGB image.

## Main MATLAB API

- `Cine(filename, 'RemoveDeadPixels', false, 'Debayer', false, 'DeadValue', [], 'BayerPattern', 'auto')`
- `OpenCineFile(filename)`
- `LoadFrame(frame_no)`
- `NextFrame(increment)`
- `CloseFile()`
- `ReplaceDeadPixels(dead_value)`
- `DebayerFrame(bayer_pattern)`
- `GetFrameRGB(frame_no, bayer_pattern)`
- `AverageFrames(start_frame, end_frame, replace, chunk_size)`
- `ModeFrames(start_frame, end_frame, replace, 'name', value, ...)`
- `LoadFramesBatch(start_frame, count)`
- `SaveFramesToNewFile(output_filename, start_frame, end_frame)`

## Internal Files

Heavy math and decode helpers are split into `Matlab/private/`:

- `cine_replace_dead_pixels.m`
- `cine_demosaic_bilinear.m`
- `cine_mode_mad_stack.m`
- `mex_unpack10bit.c`
- `mex_unpack10bit_cached.c`

Runtime shared libraries are in `Matlab/C_Files/`.

## Performance Notes

- `AverageFrames(..., chunk_size)` uses chunked accumulation to reduce overhead.
- `ModeFrames(..., 'method', 'topk')` keeps memory bounded for longer ranges.
- `ModeFrames(..., 'method', 'mad')` uses quantile/MAD rejection on a full
  stack.
- Dead-pixel repair and debayering are optional and add per-frame processing
  cost.

Detailed API notes are in `Matlab/API.md`.
