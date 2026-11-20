# Python examples

Install `cine-handler` or install the repository with `python -m pip install -e .`
from its root. Select that interpreter in your IDE, open a script and edit its
configuration under `if __name__ == "__main__":`. Paths are relative to the IDE's
working directory unless you supply absolute paths. No command-line arguments
or plotting packages are required.

| Script | Features | Inputs/dependencies |
| --- | --- | --- |
| [write_recordings.py](write_recordings.py) | Normal mono/RGB, packed10 mono/Bayer, known-count incremental writing, unknown-length generator, readback | Synthetic NumPy images; runs as supplied |
| [process_arrays.py](process_arrays.py) | Dead-pixel repair, demosaicing, mean, top-k and MAD backgrounds | Synthetic NumPy arrays; runs as supplied |
| [basic_usage.py](basic_usage.py) | Lazy opening, metadata, frame numbering, individual frames, RGB access, small batch, annotations | Set `cine_file` to a recording |
| [trim_and_background.py](trim_and_background.py) | Lossless encoded trim, mean and bounded top-k background | Set input/output paths and range |
| [convert_media.py](convert_media.py) | Ordered image files and video to normal or packed10 CINE | Install `cine-handler[media]`; configure image/video paths |
| [performance_test.py](performance_test.py) | Time opening and streaming decode throughput without retaining a video stack | Set input path and sample count |

For a first run, use `write_recordings.py`; it prints a new temporary output
directory. Point the reader, trimming or performance example at one of those
generated `.cine` files, or at your own camera recording. Output files are never
overwritten; choose a fresh destination when rerunning a conversion or trim.

The reader examples use `canonical=True` for top-down RGB coordinates. Reader
batch arrays put frames on the **last** axis, while writer stacks put them on the
**first** axis. Packed10 is lossy, including Bayer sampling for RGB input; normal
encoding preserves all uint8/uint16 image samples. See the [API](../API.md) for
full options and memory behavior.
