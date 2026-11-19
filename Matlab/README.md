# MATLAB CINE reader and writer

`Cine` and `CineWriter` use the same portable Rust backend as Python. The MEX
adapter only manages MATLAB arrays, lifetimes and array layout. Reading,
decoding, trimming, encoding, pixel processing and statistics run in Rust.
No Image Processing or Statistics Toolbox is required.

## Build on the current system

Install [Rust](https://rustup.rs/) and a C compiler supported by your MATLAB
release. In MATLAB:

```matlab
addpath('<repo>/Matlab')
mex -setup C
build_cine_backend
```

The build script locates the repository independently of the current directory,
builds Cargo's release library, and copies it under `private/lib/<architecture>`.
It builds `private/cine_mex.<mexext>` for the current MATLAB platform. The old
`build_mex_unpack10bit_cached` function remains as an alias to this build.

Build separately on macOS Apple Silicon, macOS Intel, Linux and Windows. MEX
binaries are specific to the platform and MATLAB's supported compiler/runtime;
a macOS MEX cannot run on Windows/Linux. The Rust library uses ordinary scalar
CPU instructions and requires no GPU or architecture-specific accelerator.

On Windows install the MSVC Rust toolchain and the Visual Studio C++ workload,
then configure the same compiler with `mex -setup C`. On Linux install GCC and
Rust, then run the same MATLAB build command. Build inputs are local; the Rust
crate has no third-party dependencies. If Cargo is installed outside its usual
location, put it on MATLAB's inherited `PATH`.

## Read

```matlab
cine = Cine('recording.cine', 'RemoveDeadPixels', false, 'Debayer', false);
first = cine.FileHeader.FirstImageNo;
frame = cine.PixelArray;        % first frame is decoded on demand
cine.LoadFrame(first + 1);
avg = cine.AverageFrames(first, first + 10);
bg = cine.ModeFrames(first, first + 20, false, 'method', 'topk');
cine.SaveFramesToNewFile('trim.cine', first, first + 20);
cine.CloseFile();
```

Construction reads fixed metadata only. It does not decode any image or load
the full image offset table. `ImageLocations` still returns the legacy uint64
vector including the file-size sentinel, materialized when requested.
`PixelArray`, `RawPixelArray`, color sample arrays and annotation properties
load the initial frame on first access. Explicit `LoadFrame` reads one frame.
Returned MATLAB arrays remain valid after subsequent reads or closing the file.
Explicit `CloseFile` realizes any deferred first frame, offset vector and setup
bytes before releasing the file, preserving the legacy post-close properties.
Deleting an object or reopening it releases discarded state immediately.

Existing arrays preserve storage row order and BGR channel order for
interpolated color. Raw CFA frames remain 2D unless debayering is requested.
`GetFrameRGB` provides RGB channel order. `UseMemMap`, `AssumeConstAnn` and
`Debug` remain accepted compatibility properties; Rust validates frame bounds
and handles I/O, so these properties do not select another backend.

`RedPixels`, `GreenPixels`, and `BluePixels` preserve the raw Bayer sensor
samples with NaN at the other color sites. `ModeFrames` supports mono frames;
`method='mad'` keeps the selected frame stack, while `topk` bounds memory using
`max_keep`. AverageFrames uses one Rust accumulator regardless of frame count.

## Write

```matlab
writer = CineWriter('output.cine', 640, 480, ...
    'BitDepth', 16, 'FrameRate', 1000, 'FrameCount', 100);
for k = 1:100
    writer.WriteFrame(uint16(images{k}));
end
writer.Close();
```

Input frames use top-down rows and RGB channels. Supply uint8 for `BitDepth=8`,
or uint16 for depths 9 through 16. `Channels=1` writes mono or raw Bayer;
`Channels=3` writes interpolated RGB. `CFA` selects a raw Bayer pattern.

For packed10, use `Packed10=true`, `BitDepth=12`, and uint16 mono/Bayer values
in [0,4095]. Packing applies the Phantom gamma lookup table in reverse and
quantizes to its nearest representable value. It is not lossless arbitrary
16-bit packing. For uint8 packed10 input, Rust scales [0,255] to [0,4095]. RGB input is
converted to a Bayer mosaic (RGGB by default) before packing; this also discards
two color components per sensor site. Select normal encoding for lossless RGB.

`FrameCount=0` handles unknown lengths by spooling one frame at a time and
streaming the completed CINE to its final layout on close. A known frame count
avoids that second payload copy. Output is published only by `Close`; `Abort`
or deleting an unfinished writer discards the temporary output. Existing
output paths are protected by the backend's publication policy.

```matlab
write_cine('images.cine', {'0001.png','0002.png'}, 'FrameRate', 100);
write_cine('video.cine', VideoReader('input.mp4'));
```

Video input supports formats decoded by the installed MATLAB `VideoReader`.
Image dimensions, channels and integer type must remain consistent. MATLAB's
writer emits the same format as the Python and standalone Rust APIs.

## Verify

```matlab
test_rust_backend
% Include a local corpus of genuine camera files:
test_rust_backend('/path/to/sample_cines')
```

The test covers mono/RGB 8/16-bit round trips, packed10, known/unknown lengths,
negative frame numbers, trimming, processing, annotations, statistics,
abort/close behavior, and first/middle/last frames of every supplied camera file.
