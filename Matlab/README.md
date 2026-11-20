# MATLAB CINE reader and writer

`Cine` and `CineWriter` use the same portable Rust backend as Python. The MEX
adapter only manages MATLAB arrays, lifetimes and array layout. Reading,
decoding, trimming, encoding, pixel processing and statistics run in Rust.
No Image Processing or Statistics Toolbox is required.

## Install as a MATLAB user

Download and extract the GitHub source archive or clone the repository. Keep
`Matlab/`, `binaries/`, and the Rust source/build metadata together: the installer
checks that the collected binaries match this checkout. In MATLAB:

```matlab
addpath('<repo>/Matlab')
install_cine_backend
test_rust_backend
```

This needs MATLAB and the OS-provided SHA256 utility (`shasum` on macOS,
`sha256sum` on Linux, PowerShell `Get-FileHash` on Windows), but no Python, Rust,
Cargo, C compiler, Java configuration, or additional MATLAB toolbox. The
installer verifies target, ABI,
Rust source fingerprint, artifact sizes and SHA256 checksums before copying the
matching MEX gateway and Rust library into `Matlab/private/`. Missing, corrupted
or stale binaries produce an error; the installer never compiles or downloads.
Run it again after updating the checkout, with all `Cine`/`CineWriter` objects
closed or deleted. Add the `Matlab` folder to your project path each session
(or use MATLAB's **Set Path** dialog); do not add `private/` directly.

| Collected target | MATLAB validation |
| --- | --- |
| Apple Silicon macOS (`maca64`) | MATLAB R2025b |
| Windows x64 (`win64`) | MATLAB R2026b Update 1 |
| glibc Linux x64 (`glnxa64`) | Debian 13, MATLAB R2026b Update 1 |

Other MATLAB releases have not been verified with these gateways. Each MATLAB
release also has its own OS requirements. Linux's gateway needs glibc 2.34 or
newer and MATLAB's runtime libraries; the Rust library's glibc 2.28 portability
does not extend to the MEX gateway. Intel macOS and other architectures need
separately collected artifacts. See [binary coverage](../binaries/README.md).

## Build as a developer

Install stable [Rust](https://rustup.rs/) and a C compiler supported by your
MATLAB release. For Windows use Visual Studio C++ Build Tools and Rust's MSVC
target; macOS uses Xcode Command Line Tools; Linux uses a supported GCC. In MATLAB:

```matlab
addpath('<repo>/Matlab')
mex -setup C
build_cine_backend
test_rust_backend
```

The build script locates the repository independently of the current directory,
builds Cargo's release library, and copies it under `private/lib/<architecture>`.
It builds `private/cine_mex.<mexext>` for the current MATLAB platform. The old
`build_mex_unpack10bit_cached` function remains as an alias to this build.
The Rust library uses baseline CPU instructions and requires no GPU.

Build inputs are local; the Rust crate has no third-party dependencies. If Cargo
is installed outside its usual location, put it on MATLAB's inherited `PATH`.
After changing Rust or the C gateway, rebuild and test on every supported
platform before recollecting distribution binaries. See the shared
[maintainer build guide](../docs/BUILDING.md) and
[development/commit checks](../docs/DEVELOPMENT.md). Python developer packages
are required for the all-language commit gate, not for ordinary MATLAB use.

## Read

```matlab
cine = Cine('recording.cine', 'RemoveDeadPixels', false, 'Debayer', false);
first = double(cine.FileHeader.FirstImageNo);
last = first + double(cine.FileHeader.ImageCount) - 1;
frame = cine.PixelArray;        % first frame is decoded on demand
cine.LoadFrame(min(first + 1, last));
avg = cine.AverageFrames(first, min(first + 10, last));
% ModeFrames supports mono/raw Bayer frames:
bg = cine.ModeFrames(first, min(first + 20, last), false, 'method', 'topk');
cine.SaveFramesToNewFile('trim.cine', first, min(first + 20, last));
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
`GetFrameRGB` provides RGB channel order, retaining storage row order. For
top-down display, apply `flipud` when `ImageHeader.biHeight > 0`.
`UseMemMap`, `AssumeConstAnn` and
`Debug` remain accepted compatibility properties; Rust validates frame bounds
and handles I/O, so these properties do not select another backend.

`RedPixels`, `GreenPixels`, and `BluePixels` preserve the raw Bayer sensor
samples with NaN at the other color sites. `ModeFrames` supports mono frames;
`method='mad'` keeps the selected frame stack, while `topk` bounds memory using
`max_keep`. AverageFrames uses one Rust accumulator regardless of frame count.
The background estimate is intended for bright backgrounds and is not an exact
histogram mode. Dead-pixel repair is opt-in: 4095 is the default defect marker,
but it can also be a valid saturated sample in your recording.

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
Packed10 quantization and RGB-to-Bayer sampling are irreversible; retain your
originals when the lossless normal formats are required. Output follows the CINE
format specification, but PCC playback still needs independent validation with
PCC itself; see [validation results](../docs/VALIDATION.md).

## Examples

Open these scripts in the MATLAB Editor and adjust the configuration at the
top. They generate small demonstration inputs when no input is supplied, and
choose new temporary output paths so reruns do not overwrite earlier results.
They require the backend to be installed first.

| Example | Features |
| --- | --- |
| [basic_usage.m](examples/basic_usage.m) | Lazy metadata, global frame numbers, annotations, one-frame reads, small batches, display orientation |
| [color_processing.m](examples/color_processing.m) | Raw CFA samples, dead-pixel repair, automatic Bayer pattern and RGB demosaicing |
| [processing_and_trim.m](examples/processing_and_trim.m) | Streaming mean, bounded bright-background estimate, subtraction and lossless trimming |
| [streaming_write.m](examples/streaming_write.m) | Normal/packed10 mono, RGB, known/unknown-length writing and cleanup |
| [images_and_video.m](examples/images_and_video.m) | Ordered image paths, MATLAB VideoReader, image/video-to-CINE conversion |

See [API.md](API.md) for options, shape conventions, memory behavior and lifecycle.

## Verify

```matlab
test_rust_backend
% Include a local corpus of genuine camera files:
test_rust_backend('/path/to/sample_cines')
% After collecting binaries, validate manifests and installer rejection cases:
test_prebuilt_backend
```

The test covers mono/RGB 8/16-bit round trips, packed10, known/unknown lengths,
negative frame numbers, trimming, processing, annotations, statistics,
abort/close behavior, and first/middle/last frames of every supplied camera file.
