# MATLAB API

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

With `Packed10=true`, the output depth is 12. uint8 input is scaled to linear12;
RGB input is sampled into the chosen Bayer CFA (RGGB by default). This is lossy.
`WriteFrame(frame)` appends one frame, `Close()` finalizes and publishes,
`Abort()` discards unfinished output. `FramesWritten` counts successful writes.
The destructor aborts unfinished output; explicitly close successful writes.

`write_cine(filename, frames, name, value, ...)` accepts a cell array of arrays
or image paths, a string array of image paths, or a MATLAB `VideoReader`.
Options are forwarded to `CineWriter`; dimensions/channels/type are inferred
from the first frame and VideoReader's frame rate is used by default.
