# Python interface

Install the distribution **`cine-handler`** and import **`cine_reader`**. Rust
handles CINE file I/O, decoding, writing and image processing; the Python API uses
NumPy arrays and preserves the existing reader names.

## Install for use

Use the Python interpreter selected in your IDE. For the published release:

```sh
python -m pip install --only-binary=:all: cine-handler
# Optional image and video input:
python -m pip install --only-binary=:all: 'cine-handler[media]'
```

From the **repository root** of a GitHub checkout or downloaded source archive:

```sh
python -m pip install .
# Editable installation for working directly with the Python source in an IDE:
python -m pip install -e '.[media]'
```

Use one installation method in a virtual environment. If the old `cine-reader`
distribution is installed there, uninstall it first with
`python -m pip uninstall cine-reader`; it uses the same `cine_reader` import name.

Matching wheels contain the compiled backend. Checkouts and source archives
select it from `binaries/`. Neither route needs Rust, a C compiler, MATLAB or a
GPU. Missing, stale or incompatible binaries cause a clear error instead of an
automatic compilation. The optional `images` extra installs Pillow; `video`
installs PyAV and its packaged media libraries. The default video converter does
not need an FFmpeg executable.

See [platform coverage](../binaries/README.md) for the supported architectures and
OS requirements, and [installation/build details](../docs/BUILDING.md) for the
complete procedure. Use a release containing the refactored backend; older PyPI
versions do not gain these features when repository documentation changes.

## A complete first example

This creates a tiny recording in a temporary directory, reads it back and checks
the samples. It needs no camera recording or optional image/video packages.

```python
from pathlib import Path
from tempfile import TemporaryDirectory

import numpy as np

from cine_reader import Cine, write_cine

frames = np.arange(3 * 8 * 12, dtype=np.uint16).reshape(3, 8, 12)
with TemporaryDirectory() as directory:
    path = write_cine(Path(directory) / "demo.cine", frames, frame_rate=1000, first_frame=-1)
    with Cine(path, canonical=True) as cine:
        print(cine.total_frames, cine.first_frame_number, cine.frame_rate)
        # The first image is decoded only when first accessed.
        np.testing.assert_array_equal(cine.image, frames[0])
        cine.load_frame(0)  # Acquisition frame number, not a zero-based index.
        np.testing.assert_array_equal(cine.image, frames[1])
```

For long recordings, call `load_frame` in a loop and process each `cine.image`
before loading the next. The constructor reads fixed metadata, and frames are
decoded individually. Arrays you retain remain valid after another frame loads.
Batch reads and MAD background estimation intentionally allocate multiple frames.

`canonical=True` returns top-down rows and RGB channels, matching writer input.
The default retains the historical storage-row/BGR convention. Raw Bayer images
remain 2D mosaics until demosaiced. Normal writing preserves uint8/uint16 samples;
packed10 quantizes to Phantom's nonlinear 10-bit codes, and RGB packed10 also
samples the color image into a Bayer mosaic. Existing output files are never
overwritten.

## Examples and API

Open a script from [examples/](examples/README.md) in your IDE and edit its
`if __name__ == "__main__":` configuration. Examples cover metadata and lazy
reading, color processing, trimming, backgrounds, array/image/video writing,
incremental streams and decoding throughput. The writing and array-processing
examples run without external data. No plotting package is required.

The [API reference](API.md) describes signatures, frame numbering, array layouts,
memory behavior, writer options and encoding limits. The
[validation report](../docs/VALIDATION.md) records the tested formats and platforms.

## Develop the package

An editable install lets you change Python code without compiling Rust while the
collected backend still matches its source. Full development additionally needs
Rust/Cargo, a platform linker and the tools used by the commit checks, including
MATLAB. Start with the [maintainer build guide](../docs/BUILDING.md) and install the
[per-clone commit hooks](../docs/DEVELOPMENT.md).

When Rust changes, build the current backend explicitly and regenerate the
collected binaries for each supported target before release. The manifest's
source fingerprint prevents users from silently loading an older binary with
newer Rust source. Do not work around that check by editing its checksums.
