# Local Rust, Python and MATLAB builds

The core is a dependency-free Rust crate. It uses ordinary CPU instructions,
requires no GPU, and has no `target-cpu=native` setting. Python wheels contain the
same C ABI library used by MATLAB. Build native binaries on each target OS and
CPU architecture; a macOS ARM library cannot run on Intel macOS, Linux or Windows.

## Python source checkout (IDE use)

Install stable Rust with Cargo and a platform C linker. On macOS install Xcode
Command Line Tools (`xcode-select --install`). On Linux install the distribution's
C compiler/linker toolchain. On Windows install Rust's MSVC toolchain and Visual
Studio Build Tools with **Desktop development with C++**.

From the repository root:

```sh
python -m venv .venv
# Activate .venv with your OS's normal activation command.
python -m pip install numpy pytest setuptools wheel build
python scripts/build_native.py
python -m pip install --no-build-isolation -e .
python -m pytest python/tests -q
cargo test --workspace --locked
```

`scripts/build_native.py` has `RELEASE` and `TARGET` options in its `__main__`
block for IDE execution. It copies the built library into the Python package.
If an older `cine-reader` distribution is installed in the same environment,
uninstall it first (`python -m pip uninstall cine-reader`): it shares the
`cine_reader` import name with `cine-handler`.

An uninstalled checkout also searches `target/release` and `target/debug` when its
library is not packaged. Set `PYTHONPATH=python/src` when testing that checkout
without an editable install. A normal installation never compiles during import.

`CINE_READER_LIBRARY` can point at a specific backend library for development.
It must match the current process architecture and ABI version. Each Python
reader/writer serializes access to its native handle; independent handles can
operate concurrently. The ctypes boundary releases the GIL during Rust calls.

## Standalone Rust

```sh
cargo build --workspace --release --locked
cargo test --workspace --locked
```

The crate exposes a normal Rust reader, writer and processing API, as well as
`rlib`, static library and C-compatible shared-library outputs. See
`rust/cine-core/include/cine_core.h` for the versioned C interface and buffer
ownership rules. Cargo's generated Rust documentation is available with:

```sh
cargo doc --workspace --no-deps --open
```

## Platform wheels and source distributions

```sh
python -m build --no-isolation
```

A wheel is tagged `py3-none-<platform>`: the ctypes ABI is independent of Python's
extension ABI, but the Rust binary is specific to the operating system and CPU.
The source distribution includes the Cargo workspace, lockfile and Rust sources.
Installing it requires Rust, Cargo and a linker. Installing a matching wheel does
not. No network access is needed by Cargo because the core has no dependencies.

On macOS, set `MACOSX_DEPLOYMENT_TARGET=11.0` before building to target macOS 11
or later. Build separately on Apple Silicon and Intel hardware, or install the
other Rust target and use its linker SDK. A cross-built library alone is not a
correctly tagged cross-platform wheel. Do not rename wheels to claim another
platform. On Linux, build manylinux/musllinux wheels in the corresponding build
containers and audit their native dependencies before publishing. A local
`linux_x86_64` wheel is appropriate for local installation, not a portable PyPI
Linux release. On Windows build from an x64 or ARM64 developer environment matching
Python and the Rust target. For example, native x64 builds use
`x86_64-pc-windows-msvc`.

These commands only build local artifacts. The existing release workflow has not
been migrated to a platform wheel matrix; do not publish this refactor using that
workflow until the separately planned GitHub/PyPI release work is complete.
The project version is intentionally unchanged for that later release decision.

### Linux native build

After installing stable Rust and your distribution's C linker/compiler and Python:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install numpy pytest setuptools wheel build
cargo build --release --workspace --locked
.venv/bin/python scripts/build_native.py
.venv/bin/python -m pip install --no-build-isolation -e .
.venv/bin/python -m pytest python/tests -q
.venv/bin/python -m build --no-isolation
```

The shared library is `target/release/libcine_core.so`; the standalone executable
is `target/release/cine-tool`. Use a manylinux/musllinux build environment when
preparing redistributable wheels later. This local build does not certify
compatibility with older Linux distributions.

### Windows native build

Use the MSVC Rust toolchain, Visual Studio C++ Build Tools and Python matching the
intended architecture. For an x64 Developer PowerShell, after installing them:

```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install numpy pytest setuptools wheel build
cargo build --release --workspace --locked
.\.venv\Scripts\python.exe scripts\build_native.py
.\.venv\Scripts\python.exe -m pip install --no-build-isolation -e .
.\.venv\Scripts\python.exe -m pytest python\tests -q
.\.venv\Scripts\python.exe -m build --no-isolation
```

The shared library is `target\release\cine_core.dll`; the standalone executable
is `target\release\cine-tool.exe`. Build ARM64 separately with ARM64 Python and
the corresponding Rust/MSVC toolchain. Run MATLAB's build on the same platform;
copying a macOS MEX or dylib to Windows/Linux cannot work.

## MATLAB

Run `Matlab/build_cine_backend.m` in MATLAB after configuring `mex -setup C`.
The script builds the shared Rust backend and the small MEX gateway for MATLAB's
current platform. MATLAB public classes call that gateway; it performs no CINE
parsing or pixel decoding itself. Build the MEX gateway on each supported MATLAB
platform as MEX files are specific to MATLAB's platform ABI. See `Matlab/README.md`.

## Optional image and video input

```sh
python -m pip install 'cine-handler[images]'
```

Pillow supplies image-file decoding. Install `ffmpeg` and `ffprobe` separately and
put them on `PATH` for video input. They are not needed for CINE reading, writing
NumPy images, or Rust use. Video decoding runs as a streaming subprocess. A known
image count writes directly; an unknown-length generator/video uses a temporary
spool on disk to keep memory bounded, then assembles the final CINE on close.
