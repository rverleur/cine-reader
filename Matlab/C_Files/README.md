# MATLAB Runtime Unpack Libraries

This folder contains runtime shared libraries used by `Matlab/Cine.m` for
packed 10-bit decode:

- `unpack_data_win64.dll`
- `unpack_data_win32.dll`
- `unpack_data_arm64.dylib`
- `unpack_data_elf64.so`

These binaries are the MATLAB-side runtime copies of the shared unpack helpers.
Canonical source files live in `c_src/`.

If you use the Python package, matching runtime libraries are also bundled in:

- `python/src/cine_reader/libs/`
