# Python interface

The distribution is `cine-handler`; import it as `cine_reader`. Python preserves
the existing API while Rust owns CINE I/O, decoding, encoding and processing.

For a source checkout, install Rust/Cargo and a linker, then run:

```sh
python -m pip install -e .
python -m pytest python/tests -q
```

Matching platform wheels contain the backend. They are tagged
`py3-none-<platform>`, not `py3-none-any`. No Rust installation is needed to use a
wheel. See [cross-platform build instructions](../docs/BUILDING.md).

```python
from cine_reader import Cine, write_cine

with Cine("capture.cine") as cine:
    first = cine.first_frame_number
    cine.load_frame(first)
    raw = cine.image
    average = cine.average_frames(first, min(first + 9, cine.last_frame_number))

# uint8/uint16 arrays or a generator; top-down coordinates, RGB for color.
write_cine("output.cine", frames, frame_rate=1000, encoding="normal")
```

The constructor defers first-frame decoding; accessing `image` still gives the
first frame. Offset tables, raw bytes and color-sample arrays are lazy too.
Default image coordinates/BGR order preserve existing behavior; `canonical=True`
selects top-down RGB. Normal writes are lossless; packed10 is quantized linear12
and converts RGB to a Bayer mosaic. Use `CineWriter` for incremental output,
`write_cine_from_images` with optional Pillow, or `write_cine_from_video` with
FFmpeg/FFprobe. Existing destinations are never overwritten.

See [API.md](API.md), [repository overview](../README.md) and [validation results](../docs/VALIDATION.md).
