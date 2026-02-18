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
cine = Cine(fullfile('<repo>', 'sample_data', 'TrimmedCine.cine'));
first = cine.FileHeader.FirstImageNo;
cine.LoadFrame(first);
img = cine.PixelArray;

avg = cine.AverageFrames(first, first+10, false);
bg  = cine.ModeFrames(first, first+20, false);
rgb = cine.GetFrameRGB(first, 'RGGB');

cine.SaveFramesToNewFile('trimmed_out.cine', first, first+50);
```

## API Parity With Python

The MATLAB class now includes:
- `SaveFramesToNewFile`
- `ModeFrames`
- `GetFrameRGB`
- existing methods (`LoadFrame`, `AverageFrames`, `ReplaceDeadPixels`, `LoadFramesBatch`)
