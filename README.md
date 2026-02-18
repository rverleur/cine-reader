# cine-reader

Cross-platform readers for Vision Research Phantom `.cine` files in both Python and MATLAB.

This repository contains:
- A pip-installable Python package (`cine_reader`) with bundled unpack libraries for packed 10-bit Phantom payloads.
- MATLAB code (including MEX helpers) kept in-repo for MATLAB users.
- Shared C sources used by both implementations.

## Repository Layout

```text
.
├── pyproject.toml
├── python/
│   ├── README.md
│   ├── examples/
│   ├── tests/
│   └── src/cine_reader/
├── Matlab/
│   ├── README.md
│   ├── Cine.m
│   ├── C_Files/
│   └── private/
├── c_src/
├── sample_data/
└── docs/reference/Cine File Format.pdf
```

## Python Install

```bash
pip install "git+https://github.com/<your-user>/<your-repo>.git"
```

Editable local install:

```bash
pip install -e .
```

See `python/README.md` for full Python usage and testing.

## MATLAB Usage

MATLAB files are intentionally **not** part of the Python package install.

See `Matlab/README.md` for setup, MEX build, and examples.

## Notes

- Packed 10-bit decode prefers bundled native libraries (`.dll/.so/.dylib`) and falls back to a NumPy decoder if a native library is unavailable.
- Reference format document is at `docs/reference/Cine File Format.pdf`.
- `sample_data/TrimmedCine.cine` is a local large test file and is gitignored by default.
- Frame statistics now support two robust-mode paths: legacy quantile/MAD (`method=\"mad\"`) and low-memory top-k (`method=\"topk\"`).
