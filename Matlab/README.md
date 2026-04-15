# MATLAB Reader

This folder contains the MATLAB implementation (`Cine.m`) and MEX/C-library helpers.

## Setup

1. Add this folder to MATLAB path:

```matlab
addpath(genpath('<repo>/Matlab'))
```

2. Ensure native unpack library files exist under `C_Files/`:
- `unpack_data_win64.dll` or `unpack_data_win32.dll`
- `unpack_data_arm64.dylib`
- `unpack_data_elf64.so`

3. Ensure `private/mex_unpack10bit_cached` is built for your MATLAB version.

## Build MEX (if needed)

```matlab
cd('<repo>/Matlab')
build_mex_unpack10bit_cached
```

## Usage

```matlab
cine = Cine(fullfile('<repo>', 'sample_data', 'TrimmedCine.cine'), ...
    'RemoveDeadPixels', false, 'Debayer', false);
first = cine.FileHeader.FirstImageNo;
cine.LoadFrame(first);
img = cine.PixelArray;

avg = cine.AverageFrames(first, first+10, false);
bg  = cine.ModeFrames(first, first+20, false, 'method', 'auto');
rgb = cine.GetFrameRGB(first, 'RGGB');

cine.SaveFramesToNewFile('trimmed_out.cine', first, first+50);
```

Color-enabled raw CFA/Bayer cines load as 2D sensor mosaics by default,
including packed 10-bit and normal 8/16-bit payloads. Pass `'Debayer', true`
to debayer every loaded frame, or call `DebayerFrame` on the current frame.
`RedPixels`, `GreenPixels`, and `BluePixels` contain raw CFA samples with
`NaN` at non-matching color sites.

## API Parity With Python

The MATLAB class now includes:
- `SaveFramesToNewFile`
- `ModeFrames`
- `GetFrameRGB`
- `DebayerFrame`
- existing methods (`LoadFrame`, `AverageFrames`, `ReplaceDeadPixels`, `LoadFramesBatch`)

## Internal Split

Heavy math helpers are split into `Matlab/private/`:
- `Matlab/private/cine_replace_dead_pixels.m`
- `Matlab/private/cine_demosaic_bilinear.m`
- `Matlab/private/cine_mode_mad_stack.m`

`Cine.m` remains the public entry point and orchestrates file I/O.

## Performance Hints

- `AverageFrames(..., replace, chunk_size)` uses chunked accumulation; increase `chunk_size` on high-memory machines.
- `ModeFrames(..., 'method', 'topk')` gives bounded-memory robust backgrounds for long ranges.
- `ModeFrames(..., 'method', 'mad')` uses quantile/MAD background estimation.
- Keep `replace=false` unless dead-pixel correction is required.

`ModeFrames` name/value options:
- `'method'`: `'auto' | 'mad' | 'topk'`
- `'q_bg'`: bright quantile baseline (default `0.80`)
- `'k_sigma'`: MAD rejection scale for `mad` (default `2.5`)
- `'min_keep'`: minimum accepted samples (default `3`)
- `'max_keep'`: cap for `topk` memory (default `96`, or `[]` for no cap)
- `'stack_limit'`: `auto` threshold for switching to `topk` (default `128`)

Detailed API notes are in `Matlab/API.md`.
