# Python installation and maintainer builds

The Rust backend is compiled by maintainers. Python users install a matching
wheel, or a checkout/source archive containing a matching collected library.
Normal installation and import never invoke Cargo, Rust, a C compiler, MATLAB,
or a GPU. A missing or stale binary produces an actionable error instead of
silently starting a source build.

## Python users

For a published version with the required platform wheel:

```sh
python -m pip install --only-binary=:all: cine-handler
```

For a GitHub checkout or downloaded source archive containing your target in
`binaries/`:

```sh
python -m pip install .
# Alternatively, for an IDE working directly in the checkout:
python -m pip install -e .
```

Optional image and video support also uses Python packages:

```sh
python -m pip install --only-binary=:all: 'cine-handler[media]'
# In a checkout:
python -m pip install -e '.[media]'
```

The `images` extra installs Pillow. The `video` extra installs PyAV, whose
platform wheels include the FFmpeg libraries. `media` includes both. The default
video reader streams frames through PyAV and needs no `ffmpeg` or `ffprobe`
executable. Explicit `backend="ffmpeg"` or custom executable paths retain the
optional subprocess backend for users who already manage those programs.

OS, CPU architecture and system-library compatibility matter. See
[collected targets](../binaries/README.md) for actual coverage; a macOS ARM64
library cannot satisfy a Windows or Intel macOS installation. The current Python
package version and publishing workflow still await the separate release work.
Do not treat the existing PyPI version as the newly refactored release.

If an older `cine-reader` distribution is installed in the same environment,
uninstall it first (`python -m pip uninstall cine-reader`): it shares the
`cine_reader` import name with `cine-handler`.

## Maintainer prerequisites

Building a new target or changing the Rust backend requires stable Rust/Cargo
and a platform C linker. On macOS install Xcode Command Line Tools; on Debian
install `build-essential`; on Windows install Visual Studio 2022 C++ Build Tools
with Desktop development with C++, and use the native MSVC Rust toolchain.
Match Python, Rust and the compiler environment to the intended architecture.
Leave custom target CPU flags unset; the backend uses baseline CPU instructions.
The checked-in Windows MSVC configuration statically links its C runtime so the
Rust DLL does not require a separate Visual C++ redistributable installation.
Verify Windows DLL dependencies and run the Python-only tests on Windows before
claiming that target is validated.

For all developer checks, also install FFmpeg/FFprobe for independent
interoperability tests and licensed MATLAB with a supported C compiler for the
MEX checks. Those tools are not Python runtime requirements.

To bootstrap a development checkout without a collected backend, opt into a
source build explicitly. POSIX example:

```sh
python3 -m venv .venv
CINE_BUILD_RUST=1 .venv/bin/python -m pip install -e '.[dev]'
```

Windows Developer PowerShell:

```powershell
py -3.13 -m venv .venv
$env:CINE_BUILD_RUST = '1'
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
Remove-Item Env:CINE_BUILD_RUST
```

The opt-in permits building the backend with an appropriate Rust toolchain.
It is not required by ordinary users with a matching collected library or wheel.

## Build and collect native binaries

```sh
cargo build --workspace --release --locked
cargo test --workspace --locked
python scripts/build_native.py
python -m pytest python/tests scripts/tests -q
```

Use the project virtual environment's Python for these commands. The helper
copies the native release library into the Python checkout for development.
`CINE_READER_LIBRARY` can select a development library explicitly; commit checks
set it to the freshly built staged library. Independent reader/writer handles
can operate concurrently, and ctypes releases the GIL during Rust calls.

After committing source changes and validating the native build, run:

```sh
python scripts/collect_binaries.py
```

The collector builds fresh binaries and exports the shared library, standalone
CLI, optional MATLAB gateway, and a checksummed manifest to
`binaries/<Rust target>/`. See [binary collection](../binaries/README.md) for its
IDE options, provenance and commit procedure. Runtime source checks compare a
fingerprint of the Rust inputs, not the repository commit ID, so later
Python-only or documentation commits do not invalidate an unchanged backend.

The default MATLAB collection requires a configured C compiler (`mex -setup C`)
and builds/tests `Matlab/build_cine_backend.m` on that platform. A macOS MEX
cannot run on Windows or Linux. Collection can omit MATLAB for a Python-only
artifact; all-language developer commit checks still require MATLAB.

## Wheels and source archives

With current collected artifacts:

```sh
python -m build
python -m twine check dist/*
```

Normal builds copy a validated prebuilt library without invoking Rust. Set
`CINE_BUILD_RUST=1` only when deliberately building a new backend. Wheels contain
one library and its manifest, tagged `py3-none-<platform>` because ctypes does not
require a specific CPython extension ABI. Source archives include the Rust
sources and collected native libraries, allowing Python-only installation on
the included compatible targets. They do not include compiler caches.

On macOS the library's recorded deployment target determines the wheel's OS
floor. On Linux a local Debian build is not automatically portable to older
distributions: its manifest records a conservative libc requirement. Build and
audit manylinux/musllinux wheels in the corresponding containers before broad
Linux distribution. Do not rename a wheel to claim another platform or libc.

### Linux portability

The collected x86_64 Rust backend and CLI were built with Rust 1.100.0 inside
`quay.io/pypa/manylinux_2_28_x86_64`; `binaries/x86_64-unknown-linux-gnu/build-info.json`
records the exact image digest, source fingerprint and checksums. The audited
wheel uses `py3-none-manylinux_2_28_x86_64`. Both the wheel and a clean checkout
were installed and tested without compiler tools on glibc 2.28 and Debian 13.
These artifacts do not cover musl Linux or ARM64.

For future builds, compile and test the Rust library and CLI inside the
manylinux image with an isolated Cargo target directory and baseline CPU flags.
Generate their manifest in that same environment so its libc requirement matches
the build. Copy the resulting library into the Python package and MATLAB's
companion-library directory before testing. Preserve the native MATLAB gateway
and its separately recorded requirements when assembling the collected folder.
Do not run the native collector afterward: it would replace the portable backend
with a newer host build.

Build the wheel from those collected artifacts inside the container, then audit
and repair it there (substitute the wheel produced for the intended version):

```sh
auditwheel show /path/to/cine_handler-VERSION-py3-none-linux_x86_64.whl
auditwheel repair --plat manylinux_2_28_x86_64 --only-plat \
    --wheel-dir /path/to/portable \
    /path/to/cine_handler-VERSION-py3-none-linux_x86_64.whl
```

Inspect the repaired wheel again and verify its library SHA256 against the
packaged manifest. For the current std-only Rust build, auditwheel leaves the
library unchanged and adds no bundled shared libraries. If a future repair
changes the library, regenerate the packaged checksums and repeat runtime tests
before distributing it. Renaming a wheel is not a substitute for this audit.

The MATLAB R2026b gateway was compiled separately on Debian 13 with GCC 14.2.
Its imported glibc symbols reach 2.34, and it also requires MATLAB's `libmx.so`
and `libmex.so`. Only its Debian 13/MATLAB R2026b runtime has been verified; the
Python backend's manylinux claim does not extend to the MATLAB gateway.

The existing release workflow has not been migrated to a native wheel matrix.
Do not publish this refactor through that workflow until the separately planned
GitHub/PyPI release work is complete.

## Standalone Rust

The crate exposes reader, writer and processing APIs, a CLI, and `rlib`, static
library and C-compatible shared-library outputs. Python is not required for
Rust API or CLI use. See `rust/cine-core/include/cine_core.h` for the C ABI and
buffer ownership rules, or generate Rust API documentation:

```sh
cargo doc --workspace --no-deps --open
```
