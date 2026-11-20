# Python API

The package is installed as `cine-handler` and imported as `cine_reader`.
[Installation](README.md) and [IDE examples](examples/README.md) accompany this
reference. All paths accept strings or `pathlib.Path` objects.

## Reader lifecycle and frame numbering

```python
from cine_reader import Cine

with Cine("capture.cine", canonical=True) as cine:
    first = cine.first_frame_number
    cine.load_frame(first)
    pixels = cine.image
```

```python
Cine(filename, keep_annotations=True, *, remove_dead_pixels=False,
     debayer=False, dead_value=None, dead_is_threshold=True,
     bayer_pattern="auto", canonical=False)
```

| Option | Meaning |
| --- | --- |
| `keep_annotations` | Retain loaded frame annotation bytes. |
| `remove_dead_pixels` | Repair each loaded image before optional demosaicing. |
| `debayer` | Convert raw Bayer frames to RGB on load. |
| `dead_value` | Marker/threshold; `None` infers it from camera setup. |
| `dead_is_threshold` | Repair values `>= dead_value`; `False` repairs exact matches. |
| `bayer_pattern` | `"auto"`, `"RGGB"`, `"BGGR"`, `"GRBG"` or `"GBRG"`. |
| `canonical` | Use top-down rows and RGB channel order. |

Frame methods take **acquisition frame numbers**, which can be negative and run
from `first_frame_number` through `last_frame_number`, inclusive. They are not
zero-based array indices unless the recording starts at zero.

`open_cine_file(filename)` reopens this object on another recording.
`close_file()` closes its handle; a `with` block calls this automatically.
Construction reads fixed metadata and defers the first decode until `image`,
`frame`, `pixel_array` or another pending frame attribute is accessed. Explicit
`load_frame` decodes immediately. Frame offsets, raw payload bytes, setup bytes
and color-sample arrays are also loaded on demand.

Each returned NumPy image owns its memory, so a saved array survives later frame
loads. Explicit close and context exit materialize deferred first-frame and raw
metadata state for compatibility with post-close access. Destruction and
reopening discard pending state without decoding it. Use one reader per
independent worker; do not call one reader concurrently.

## Frames, orientation and color

| Member | Result or action |
| --- | --- |
| `load_frame(image_no, *, convert_bgr_to_rgb=False)` | Load one frame; returns `None`. Read `image` afterward. |
| `next_frame(increment=1, *, convert_bgr_to_rgb=False)` | Move relative to `current_frame`; negative steps are allowed within the recording. |
| `image`, `frame`, `pixel_array` | Current `[H,W]` mono/raw image or `[H,W,3]` color image. |
| `pixel_data` | Flattened current pixel array. |
| `current_frame` | Current acquisition frame number. |
| `load_frames_batch(start_frame, count)` | Allocate `[H,W,N]` or `[H,W,3,N]`, with frames on the **last** axis. |
| `annotation_data`, `annotation` | Full retained annotation block and its payload. |
| `image_data` | Original encoded image payload bytes, fetched lazily. |
| `image_size`, `annotation_size` | Stored payload/block sizes. |

Normal samples decode as uint8 or uint16 according to the file. Packed10 decodes
to linear12 values in a uint16 array through Phantom's lookup table. Packed12
and raw CFA reading are supported; proprietary CCI compression is not.

By default, storage-row order and BGR channel order preserve the previous API,
including bottom-up rows in ordinary positive-height uncompressed recordings.
Prefer `canonical=True` for new analysis and comparisons with input images.
`convert_bgr_to_rgb=True` changes channel order only, not row orientation.

Raw CFA/Bayer images are 2D until demosaiced. `red_pixels`, `green_pixels` and
`blue_pixels` lazily expose `[H,W]` float sensor-sample arrays with `NaN` at sites
belonging to the other colors; these remain based on the original mosaic after
demosaicing. For interpolated three-channel images they expose their channels;
for monochrome images they are `None`.

### Processing the current frame

```python
cine.replace_dead_pixels(dead_value=None, dead_is_threshold=True)
cine.debayer_frame(bayer_pattern="auto")
rgb = cine.get_frame_rgb(image_no=None, bayer_pattern="auto")
```

`replace_dead_pixels` updates the current image. Mono repair uses valid adjacent
neighbors, Bayer repair uses neighbors of the same Bayer phase, and RGB repair
operates per channel. An inferred packed10 threshold is converted through the
lookup table before comparing with decoded linear values.

`debayer_frame` updates the current mosaic to RGB; use it only for raw Bayer data
(it also normalizes a loaded three-channel BGR image to RGB).
`get_frame_rgb` returns a converted array without replacing the current image;
an optional `image_no` first loads that frame. For 2D data it uses the requested
or metadata-derived Bayer pattern, falling back to RGGB when metadata has none.
For an ordinary monochrome image, use `image` directly instead of demosaicing it.

## Statistics and trimming

```python
mean = cine.average_frames(start_frame, end_frame, replace_dead_pixels=False, chunk_size=8)
background = cine.mode_frames(
    start_frame,
    end_frame,
    replace_dead_pixels=False,
    method="auto",
    q_bg=0.80,
    k_sigma=2.5,
    min_keep=3,
    max_keep=96,
    stack_limit=128,
)
cine.save_frames_to_new_file(output_filename, start_frame, end_frame)
```

All ranges are inclusive. Mean estimation retains one Rust accumulator; the
positive `chunk_size` argument remains accepted for API compatibility and does
not allocate a chunk stack. Its output uses the current frame's dtype. Statistics
preserve the historical rounding to the nearest integer with ties to even.

Despite its historical name, `mode_frames` estimates a **bright background**,
not a histogram mode. `method="mad"` stores all samples for quantile/MAD rejection.
`"topk"` retains the brightest samples, bounded by `max_keep`; setting
`max_keep=None` removes that cap. `"auto"` selects MAD up to `stack_limit` frames
and top-k above it. `q_bg` is a quantile in `(0,1)`, `k_sigma` is the MAD multiplier
and `min_keep` controls minimum retained samples. Output is uint16 and supports
mono and color shapes. These operations load through the reader and leave its
current-frame state at the last processed frame.

Trimming copies the original encoded frames, preserves acquisition numbers and
adjusts known per-frame time tags. It does not re-encode images or bake any
processing into the file. The output path must not already exist.

## Metadata

| Convenience property | Meaning |
| --- | --- |
| `first_frame_number`, `total_frames`, `last_frame_number` | Acquisition frame range and count. |
| `frame_rate` | Best available setup frame rate, in Hz. |
| `exposure_time_ns` | Exposure in nanoseconds. |
| `exposure_time_seconds`, `exposure_time` | Exposure in seconds. |
| `recording_datetime`, `recording_date` | Recording timestamp/date when available. |
| `cfa_code`, `bayer_pattern` | CFA identifier and inferred Bayer layout. |

The metadata objects preserve specification-style names:

| Object/type | Example fields |
| --- | --- |
| `file_header` / `CineHeader` | `FirstImageNo`, `ImageCount` |
| `image_header` / `BitmapHeader` | `biWidth`, `biHeight`, `biBitCount`, `biCompression` |
| `camera_setup` / `Setup` | `FrameRate`, `ShutterNs`, `RealBPP`, `WhiteLevel`, `CFA`, `SetupData` |
| `image_locations` / `ImageOffsets` | `pImage`, `pImageData` |

Accessing `image_locations` materializes the offset table; `pImage` includes a
trailing file-end sentinel. Leave it lazy when only individual frames are needed.
Recording timezones use the specification's seconds-west-of-UTC convention:
`RecordingTimeZone=14400` means UTC-04:00.

## Writing array sequences and streams

```python
from cine_reader import CineWriter, write_cine

# Arrays: top-down mono [H,W] or RGB [H,W,3], using uint8 or uint16.
output = write_cine("normal.cine", frames, frame_rate=1000, first_frame=-20)
output = write_cine("packed.cine", frames, encoding="packed10", frame_rate=1000)

with CineWriter(
    "stream.cine",
    width=640,
    height=480,
    dtype="uint16",
    channels=1,
    frame_count=100,
    frame_rate=1000,
) as writer:
    for frame in source:
        writer.write_frame(frame)
```

`frames` is an iterable of arrays. A NumPy stack is iterated on its **first**
axis: `[N,H,W]` or `[N,H,W,3]`. This differs from reader batches; convert one with
`np.moveaxis(batch, -1, 0)` before writing. Dimensions, channels and dtype must
stay identical through a sequence. No resizing or float-to-integer conversion
is done implicitly.

```python
CineWriter(filename, *, width, height, dtype=np.uint16, channels=1,
           encoding="normal", frame_count=None, frame_rate=30.0,
           first_frame=0, bit_depth=None, cfa=0)
```

| Option | Behavior |
| --- | --- |
| `width`, `height` | Positive image dimensions. |
| `dtype` | uint8 or uint16; each appended frame must match. |
| `channels` | `1` for mono/raw Bayer; `3` for RGB. |
| `encoding` | `"normal"` or `"packed10"`. |
| `frame_count` | Exact positive count, or `None` for an unknown-length stream. |
| `frame_rate` | Positive finite constant acquisition rate. |
| `first_frame` | First acquisition number, including negative values. |
| `bit_depth` | Normal: 8 for uint8, 9–16 for uint16; default follows dtype. Packed10: 12. Values must fit the meaningful depth. |
| `cfa` | `0` for mono/normal RGB; Bayer `3=GBRG`, `4=RGGB`, `5=GRBG`, `6=BGGR`. |

`write_cine` infers dimensions/channels/dtype from the first image and accepts the
remaining writer options. It infers an exact count from sized collections.
Both this helper and `CineWriter` process images incrementally. Unknown-length
streams use a temporary disk spool and a final copy; an exact count avoids that
extra disk pass. `frames_written` reports the appended count.

Successful `close()` or context exit finalizes and publishes a complete file.
`abort()` or an exceptional context exit discards temporary output. A short
declared sequence fails finalization. Existing destinations are never replaced.
All writing helpers return the completed output `Path`.

### Encoding choices

Normal writing preserves all samples, including RGB24/RGB48. Packed10 stores
Phantom P10 codes, **not simple linear 10-bit truncation**. Uint16 input must
contain linear values in `0..4095`, quantized to the nearest entry of Phantom's
12-bit lookup table; values below its first entry clamp to that entry. Uint8
input is first scaled to `0..4095`.

RGB packed10 also samples one color per Bayer site, losing two color samples
per pixel in addition to quantization. RGGB (`cfa=4`) is its default pattern.
For a mono-shaped raw Bayer image, supply its CFA explicitly. Partial groups
are padded in the file and discarded when reading. Packed12 reading is supported,
but packed12 writing is not offered.

## Image-file and video conversion

```python
from cine_reader import write_cine_from_images, write_cine_from_video

write_cine_from_images("photos.cine", ordered_image_paths, frame_rate=30)
write_cine_from_video("video.cine", "input.mp4", encoding="normal")
```

`write_cine_from_images(filename, image_paths, **options)` requires Pillow
(`cine-handler[images]`) and retains the supplied path order. It supports
grayscale, 16-bit grayscale and RGB images, converts palette images to RGB, and
discards alpha channels. Images must agree in shape and dtype.

```python
write_cine_from_video(filename, video_filename, *, encoding="normal",
                      grayscale=False, frame_rate=None,
                      ffmpeg="ffmpeg", ffprobe="ffprobe", backend=None, **options)
```

The default backend is PyAV (`cine-handler[video]`), whose wheels provide the
media libraries without separate executable tools. It decodes the first video
stream as RGB8 or gray8 one frame at a time; audio is ignored. Stored pixel
orientation is retained and rotation metadata is not applied. The output has a
constant frame rate; supply `frame_rate` when converting variable-rate input.
Normal encoding preserves these decoded samples, not the source video's codec
or original high-bit-depth representation.

Explicit `backend="ffmpeg"`, or custom `ffmpeg`/`ffprobe` paths without a backend
override, selects the optional subprocess backend and requires those tools to
be installed separately. `backend="pyav"` explicitly selects PyAV. Writer
options such as `first_frame` are forwarded through `**options`.

## Array-only helpers

These public helpers use the same Rust backend without opening a CINE file:

| Helper | Purpose |
| --- | --- |
| `replace_dead_pixels(frame, *, dead_value=4095, dead_is_threshold=False, bayer_raw=False)` | Repair mono, raw Bayer or color arrays. |
| `replace_dead_pixels_mono`, `replace_dead_pixels_bayer`, `replace_dead_pixels_rgb` | Explicit repair variants accepting `frame`, `dead_value=4095` and keyword-only `dead_is_threshold=False`. |
| `demosaic_bilinear(frame, pattern="RGGB")` | Convert a 2D Bayer array into RGB. |
| `average_from_frame_iter(frames, *, out_dtype=None, chunk_size=8)` | Return `(mean, count)` using one accumulator; output defaults to the first frame dtype. |
| `robust_background_mad_stack(frames, *, q_bg=0.80, k_sigma=2.5, min_keep=3, out_dtype=np.uint16)` | Full-stack bright-background estimate. |
| `robust_background_topk(frames, *, frame_count, q_bg=0.80, min_keep=3, max_keep=96, out_dtype=np.uint16)` | Bounded retained-sample background estimate. |
| `unpack_10bit_data(data)` | Decode each complete five-byte group into four linear uint16 samples through Rust. |
| `unpack_10bit_numpy(data)` | NumPy reference implementation retained for compatibility/comparison. |

Repair/demosaic helpers return processed arrays. Statistics round their estimates
to integer sample values with ties to even, even when a floating `out_dtype` is
requested. Low-level unpack helpers ignore incomplete trailing groups; use
`Cine` to handle complete frame dimensions and any padded packed10 samples.

Writer output follows the supplied CINE specification and has independent
reader/FFmpeg checks. PCC itself has not been tested; see the
[validation record](../docs/VALIDATION.md) before assuming compatibility with a
particular PCC release.
