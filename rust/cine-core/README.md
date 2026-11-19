# cine-core

A dependency-free Rust library and command-line tool for CINE files. It supports
v0/v1 indexes, mono8/16, RGB24/48, raw CFA, packed10 gamma expansion, packed12,
frame annotations and lossless trimming. Proprietary CCI is not supported.

`Reader::open` reads fixed metadata without scanning the image index. Offsets
are fetched as needed; packed decoding reuses one scratch buffer. Callers can
reuse an output allocation:

```rust,no_run
use cine_core::Reader;

fn main() -> cine_core::Result<()> {
    let mut reader = Reader::open("capture.cine")?;
    println!("{:?} {:?}", reader.info, reader.metadata());
    let mut pixels = vec![0u8; reader.info.decoded_bytes as usize];
    for index in 0..reader.info.frame_count {
        // 3: top-down RGB; 0: source row order and BGR.
        reader.read_frame_into(index, 3, &mut pixels)?;
        // Process here. uint16 samples are little endian.
    }
    Ok(())
}
```

`read_frame(index)` allocates and returns a canonical frame. `block_len` and
`block_into` expose file/bitmap/setup bytes, annotations and source payloads;
see the block identifiers in `include/cine_core.h`. `trim(path, start, count)`
copies encoded frames and adjusts known per-image metadata without decoding.

The writer accepts tightly packed, top-down images. Supply a known frame count
to avoid a disk spool; zero means unknown. `finish` publishes the output. Dropping
an unfinished writer removes temporary files. Existing output is never replaced.

```rust,no_run
use cine_core::writer::{CineWriter, WriterOptions};

fn main() -> cine_core::Result<()> {
    let options = WriterOptions {
        width: 640, height: 480, bit_depth: 8, channels: 3,
        frame_count: 2, frame_rate: 30.0,
        ..WriterOptions::default()
    };
    let mut writer = CineWriter::create("output.cine", options)?;
    let rgb = vec![0u8; 640 * 480 * 3];
    writer.write_frame(&rgb)?;
    writer.write_frame(&rgb)?;
    writer.finish()
}
```

For packed10, set `packed10=true`, `channels=1`, `bit_depth=12` and supply
linear12 little-endian u16 samples. `write_image(bytes, sample_bytes, channels)`
also accepts uint8 and RGB: Rust scales uint8 and samples RGB into the configured
CFA (`cfa=4` is RGGB). Values outside `0..4095` in u16 input are rejected. The
inverse LUT quantizes to the nearest representable value.

The core targets the platform's baseline CPU, with no GPU, thread pool or external
codec dependency. Independent readers can run on separate threads; a single
handle requires serialized access. C callers own output buffers and must obey
the valid-handle, length and non-overlap rules in `include/cine_core.h`. Errors
and panics are contained at that ABI boundary.

The CLI provides `info`, `verify`, `extract` and `transcode`. Image/video file
codecs are supplied by the optional Python/MATLAB frontends; Rust consumes and
produces image samples directly. See the repository build guide for other OSes.
