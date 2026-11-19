# Python API Notes

## Reader Lifecycle

```python
from cine_reader import Cine

with Cine("sample_data/TrimmedCine.cine") as cine:
    cine.load_frame(cine.first_frame_number)
    frame = cine.image
```

- `Cine(filename, keep_annotations=True, remove_dead_pixels=False, debayer=False, dead_value=None, dead_is_threshold=True, bayer_pattern="auto")`
  - `remove_dead_pixels`: when `True`, repair dead pixels on every `load_frame`.
  - `debayer`: when `True`, debayer raw CFA/Bayer frames on every `load_frame`.
  - `bayer_pattern`: `auto` or one of `RGGB`, `BGGR`, `GRBG`, `GBRG`.
- `open_cine_file(filename)`
  - `filename`: path to `.cine`.
- `close_file()`
  - closes active file handle.

## Frame Access

- `load_frame(image_no, convert_bgr_to_rgb=False)`
  - `image_no`: global frame number (`file_header.FirstImageNo .. last_frame_number`).
  - `convert_bgr_to_rgb`: channel-order conversion for 3-channel payloads.
- `next_frame(increment=1, convert_bgr_to_rgb=False)`
  - `increment`: frame-number step (can be negative).
- `image` / `frame`
  - alias for latest decoded pixel array (`pixel_array`).
  - raw CFA/Bayer payloads remain 2D unless `debayer=True` or `debayer_frame()` is used.
- `red_pixels` / `green_pixels` / `blue_pixels`
  - `None` for mono frames.
  - for raw CFA/Bayer color frames, `[H, W]` float arrays with actual sensor samples at that color's sites and `NaN` elsewhere.
- `load_frames_batch(start_frame, count)`
  - `start_frame`: first frame number in range.
  - `count`: number of consecutive frames.
  - output shape:
    - mono or raw CFA: `[H, W, N]`
    - debayered/interpolated color: `[H, W, 3, N]`

## Image Processing

- `replace_dead_pixels(dead_value=None, dead_is_threshold=True)`
  - `dead_value`: marker/threshold for dead pixels. If `None`, inferred from setup (`WhiteLevel + 1`, then `RealBPP` max).
  - `dead_is_threshold`: when `True`, treat values `>= dead_value` as dead.
  - behavior by frame type:
    - mono 2D: 8-neighbor repair
    - raw Bayer/CFA 2D: repair each 2x2 phase separately before demosaic
    - RGB/BGR 3D: repair each channel independently
- `debayer_frame(bayer_pattern="auto")`
  - mutates the current raw CFA/Bayer `pixel_array` into RGB `[H, W, 3]`.
- `get_frame_rgb(image_no=None, bayer_pattern="auto")`
  - `image_no`: optional frame number to load first.
  - `bayer_pattern`: `auto` or one of `RGGB`, `BGGR`, `GRBG`, `GBRG`.

## Statistics

- `average_frames(start_frame, end_frame, replace_dead_pixels=False, chunk_size=8)`
  - `start_frame`, `end_frame`: inclusive frame range.
  - `replace_dead_pixels`: apply dead-pixel correction before averaging.
  - `chunk_size`: chunked accumulation size for bounded-memory averaging.
- `mode_frames(start_frame, end_frame, replace_dead_pixels=False, method="auto", q_bg=0.80, k_sigma=2.5, min_keep=3, max_keep=96, stack_limit=128)`
  - `method`: `auto | mad | topk`.
  - `q_bg`: bright-background quantile threshold.
  - `k_sigma`: MAD rejection multiplier (`mad` mode).
  - `min_keep`: minimum accepted samples per pixel.
  - `max_keep`: top-k cap (`topk` mode).
  - `stack_limit`: switch threshold for `auto`.
  - supports mono and RGB frame stacks.

## File Utilities

- `save_frames_to_new_file(output_filename, start_frame, end_frame)`
  - `output_filename`: destination `.cine` path.
  - `start_frame`, `end_frame`: inclusive frame range to copy.

## Useful Top-Level Metadata Aliases

- `first_frame_number` -> `file_header.FirstImageNo`
- `total_frames` -> `file_header.ImageCount`
- `last_frame_number` -> derived
- `frame_rate` -> best available setup frame rate
- `exposure_time_ns` / `exposure_time_seconds` / `exposure_time`
- `recording_datetime` / `recording_date`
- `cfa_code` / `bayer_pattern`

## Specification-Aligned Metadata Objects

Field names inside these objects intentionally follow CINE/BITMAP naming:

- `file_header` (`CineHeader`)
- `image_header` (`BitmapHeader`)
- `camera_setup` (`Setup`)
- `image_locations` (`ImageOffsets`)

Examples of spec-style fields:

- `file_header.FirstImageNo`
- `file_header.ImageCount`
- `image_header.biWidth`
- `image_header.biBitCount`
- `camera_setup.FrameRate`
- `camera_setup.ShutterNs`
- `camera_setup.RealBPP`

## Rust backend and lazy access

The existing reader signatures and metadata names remain available. Opening a
`Cine` parses fixed metadata only; its first frame is decoded when an existing
frame attribute such as `image` or `pixel_array` is first accessed. Explicit
`load_frame` decodes immediately. Offset arrays, tagged setup bytes and the three
color sample arrays are loaded only when accessed. The core owns file I/O and
reusable payload buffers. Each returned NumPy frame owns its memory, so retaining
a frame across subsequent loads is safe. Explicit `close_file()` and context
exit materialize any pending first frame and raw metadata so those existing
attributes remain usable after close. Destruction and reopening simply release
the old native handle without reading deferred state.

`Cine(path, canonical=True)` is an additional option: it returns top-down images
and RGB color order. The default preserves the previous storage-row/BGR order,
including bottom-up rows for positive-height uncompressed CINE. Use canonical
mode when comparing images with input arrays passed to the writer. Packed raw
frames remain raw mosaics unless debayering is requested.

## Writing images and videos

```python
from cine_reader import Cine, CineWriter, write_cine, write_cine_from_images, write_cine_from_video

# frames: iterable of uint8/uint16 [H,W] or RGB [H,W,3] arrays.
write_cine("normal.cine", frames, frame_rate=1000, first_frame=-20)
write_cine("packed.cine", frames, encoding="packed10", frame_rate=1000)
write_cine_from_images("photos.cine", sorted(image_paths), frame_rate=30)
write_cine_from_video("video.cine", "input.mp4")

with Cine("normal.cine", canonical=True) as cine:
    image = cine.image

with CineWriter(
    "stream.cine", width=640, height=480, dtype="uint16", frame_count=100, frame_rate=1000
) as writer:
    for frame in source:
        writer.write_frame(frame)
```

- Writer input always uses top-down rows and RGB order.
- `encoding="normal"` preserves uint8/uint16 values, including RGB24/RGB48.
  `bit_depth` describes the meaningful sample bits (default 8 or 16).
- `encoding="packed10"` implements Phantom P10, **not linear 10-bit truncation**:
  uint16 samples must be linear values in 0..4095 and are quantized to the nearest
  entry of Phantom's 12-bit lookup table. Values below the table's first entry
  are clamped to that entry. uint8 samples are scaled to 0..4095 first.
- RGB packed10 input is sampled to a Bayer mosaic. This loses two color samples
  per pixel in addition to P10 quantization. Use normal RGB for exact color
  preservation. `cfa=4` (RGGB) is the default for RGB packed10; CFA 3, 5 and 6
  select GBRG, GRBG and BGGR. For a mono-shaped raw Bayer array specify its CFA.
- Partial packed10 groups are padded in the file and discarded on decoding.
  Images in a sequence must have identical dimensions, channels and dtype.
  No silent resizing occurs.
- `CineWriter(..., frame_count=None)` supports unknown-length streams with a
  temporary disk spool. Supplying the exact count avoids that extra disk pass.
  `write_cine` automatically uses the length of sized collections and NumPy stacks.
- A successful `close()` or context exit publishes a complete output. A failed
  write, short declared sequence, or exceptional context exit removes temporary
  data. Existing destinations are never overwritten. `abort()` discards a stream.
- Image files require the optional `images` extra (Pillow). Supplied order is
  retained. Palette images become RGB; alpha channels are discarded.
- Video input needs FFmpeg/FFprobe, selects the first video stream, and decodes
  RGB8 (or `grayscale=True` gray8) one frame at a time. Stored pixel orientation
  is retained; video rotation metadata is not applied. Audio is ignored. The output
  has a constant frame rate; supply `frame_rate=` when converting variable-rate
  input. The optional `ffmpeg=` and `ffprobe=` parameters select tool paths.

Writer output follows the supplied CINE specification. An end-to-end PCC open
check must be performed on a Windows system with PCC before claiming tested
compatibility with a particular PCC release.

For packed10 files, automatic dead-pixel thresholds now convert `WhiteLevel`
through the Phantom lookup table before comparing it with decoded linear pixels.
This corrects the old comparison between encoded 10-bit and decoded 12-bit values.

Recording timezone decoding now follows the specification's seconds-west-of-UTC
convention. For example, `RecordingTimeZone=14400` yields UTC-04:00.
