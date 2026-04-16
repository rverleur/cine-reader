# cine-reader

Cross-platform readers for Vision Research Phantom `.cine` files in Python
and MATLAB.

GitHub repository:

- `https://github.com/rverleur/cine-reader`

This repository contains:

- a Python package, `cine_reader`
- a MATLAB reader, `Matlab/Cine.m`
- shared C sources and runtime unpack libraries for packed 10-bit payloads

## Python Installation

There is currently no PyPI package. Install from a GitHub release, from the
Git repo, or from a local checkout.

### Recommended: install from a GitHub release

1. Open the Releases page for the repo.
2. Download the wheel for the release you want:
   `cine_reader-X.Y.Z-py3-none-any.whl`
3. Install it with:

```bash
pip install cine_reader-X.Y.Z-py3-none-any.whl
```

You can also install directly from a release asset URL:

```bash
pip install "https://github.com/rverleur/cine-reader/releases/download/vX.Y.Z/cine_reader-X.Y.Z-py3-none-any.whl"
```

You can install the source distribution from the release too:

```bash
pip install cine_reader-X.Y.Z.tar.gz
```

### Install the latest GitHub version

```bash
pip install "git+https://github.com/rverleur/cine-reader.git"
```

### Install from a local checkout

```bash
pip install .
```

For editable development installs:

```bash
pip install -e .
```

## Python Notes

- Python package code lives under `python/src/cine_reader/`.
- Packed 10-bit decode prefers bundled native unpack libraries and falls back
  to a NumPy implementation if a native helper is unavailable.
- Raw color CFA/Bayer cines load as 2D sensor mosaics by default.
- Set `debayer=True` to debayer every loaded frame.
- Set `remove_dead_pixels=True` to repair dead pixels every loaded frame.
- `red_pixels`, `green_pixels`, and `blue_pixels` expose raw CFA sensor
  samples with `NaN` at non-matching color sites.

See [python/README.md](python/README.md) for Python usage and
[python/API.md](python/API.md) for API details.

## MATLAB Usage

MATLAB files are kept in-repo and are not installed by the Python wheel.

Use the MATLAB reader directly from this checkout or from a source archive:

1. Clone or download the repository.
2. Add `Matlab/` to your MATLAB path.
3. Build `mex_unpack10bit_cached` if you need packed 10-bit support on your
   local MATLAB installation.

See [Matlab/README.md](Matlab/README.md) for MATLAB setup and usage.

## Repository Layout

```text
.
├── pyproject.toml
├── README.md
├── python/
│   ├── README.md
│   ├── API.md
│   ├── examples/
│   ├── tests/
│   └── src/cine_reader/
├── Matlab/
│   ├── README.md
│   ├── API.md
│   ├── Cine.m
│   ├── C_Files/
│   └── private/
├── c_src/
├── sample_data/
└── docs/reference/Cine File Format.pdf
```

## Runtime Libraries

The Python wheel and the MATLAB repo include runtime unpack helpers for packed
10-bit CINE data:

- `unpack_data_win32.dll`
- `unpack_data_win64.dll`
- `unpack_data_elf64.so`
- `unpack_data_arm64.dylib`

If a matching native helper cannot be loaded, Python falls back to the NumPy
decoder.

## Reference and Sample Data

- Format reference: `docs/reference/Cine File Format.pdf`
- Local smoke-test sample path: `sample_data/TrimmedCine.cine`

The sample cine file is intentionally gitignored and not distributed in the
repository.
