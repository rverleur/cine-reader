# Installation and maintainer builds

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
library cannot satisfy a Windows or Intel macOS installation. This guide covers
0.2.0; use its checkout until that version is published on PyPI.

If an older `cine-reader` distribution is installed in the same environment,
uninstall it first (`python -m pip uninstall cine-reader`): it shares the
`cine_reader` import name with `cine-handler`.

## MATLAB users

Obtain the complete checkout or source archive, including `binaries/`, and run
from the repository root in MATLAB:

```matlab
addpath(fullfile(pwd, 'Matlab'));
install_cine_backend;
```

The installer validates and copies the matching collected gateway/library; it
never invokes Rust, Python or a C compiler. Keep `Matlab/` on the path for each
session, or save it through MATLAB's path settings. Close all `Cine` and
`CineWriter` objects before replacing an installed backend. Use the platform and
MATLAB compatibility details in [Matlab/README.md](../Matlab/README.md).

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

### macOS

Install native-architecture Python, Git and FFmpeg/FFprobe. If you use Homebrew,
`brew install python git ffmpeg` provides those tools. Install Apple's linker
and the official Rust toolchain:

```sh
xcode-select --install
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh
. "$HOME/.cargo/env"
rustup component add rustfmt clippy
```

Complete the Xcode tools installer before compiling. Use ARM64 Python/Rust on
Apple Silicon (not a Rosetta Intel shell). An Intel build needs an Intel target,
linker configuration and runtime validation; the collected ARM64 binary cannot
be relabeled as universal or Intel.

### Debian/Ubuntu Linux

```sh
sudo apt-get update
sudo apt-get install -y build-essential pkg-config python3-venv git curl ca-certificates ffmpeg
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh
. "$HOME/.cargo/env"
rustup component add rustfmt clippy
```

For portable release builds also install Podman or Docker and use the manylinux
procedure below. A native build on a recent distribution is suitable for local
development but cannot claim an older glibc compatibility floor.

### Windows x64

Install 64-bit Python, Git for Windows, FFmpeg/FFprobe, and Visual Studio 2022
Build Tools with **Desktop development with C++**, the x64 MSVC tools and a
Windows SDK. Install Rust with the official [rustup installer](https://rust-lang.org/tools/install/)
and select the MSVC host target. Open **Developer PowerShell for VS 2022**:

```powershell
rustup default stable-x86_64-pc-windows-msvc
rustup component add rustfmt clippy
rustc -vV
Get-Command cl.exe, link.exe, ffmpeg.exe, ffprobe.exe
```

`link.exe` must be Microsoft's linker. Git for Windows also supplies an unrelated
program with that name. If it is selected first, set an explicit linker for the
current shell after entering the Visual Studio developer environment:

```powershell
$env:CARGO_TARGET_X86_64_PC_WINDOWS_MSVC_LINKER = Join-Path $env:VCToolsInstallDir 'bin\Hostx64\x64\link.exe'
```

If Windows blocks `Launch-VsDevShell.ps1`, use the x64 Native Tools Command Prompt
shortcut, or permit signed/local scripts for the current PowerShell session with
`Set-ExecutionPolicy -Scope Process -ExecutionPolicy RemoteSigned` and relaunch
that trusted Visual Studio script. Do not run development commands as another
user merely to work around a PATH or execution-policy problem.

### Clone and configure Python

```sh
git clone https://github.com/rverleur/cine-reader.git
cd cine-reader
```

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
Activate the environment (`. .venv/bin/activate` on POSIX, or use the explicit
`.venv\Scripts\python.exe` path on Windows) for subsequent Python commands.

Install/activate MATLAB in a desktop session and run `mex -setup C` once. Then
configure the commit gate from the project environment:

```sh
python scripts/install_hooks.py
```

For a nonstandard MATLAB location, configure `MATLAB` in that script's
`__main__` block before running it. Details and the complete required checks are
in [DEVELOPMENT.md](DEVELOPMENT.md). Rust's official [installation guide](https://rust-lang.org/tools/install/)
provides alternative installation methods.

## Build and collect native binaries

```sh
cargo build --workspace --release --locked
cargo test --workspace --locked
python scripts/build_native.py
python -m pytest python/tests scripts/tests -q
```

Use the project virtual environment's Python for these commands. The helper
copies the native release library into the Python checkout for development.
Restart an IDE Python kernel that has loaded the old library before testing the
new one. In MATLAB run `build_cine_backend; test_rust_backend` after closing
existing reader/writer handles.
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

With current collected artifacts, the release helper creates and validates a
clean host wheel and source archive without compiling Rust:

```sh
python scripts/release.py
```

See [RELEASING.md](RELEASING.md) for its modes, Linux auditing dependencies,
output locations and the GitHub build matrix. For a local packaging experiment,
`python -m build` remains available, but its Linux wheel needs auditwheel repair
before PyPI distribution.

Normal builds copy a validated prebuilt library without invoking Rust. Set
`CINE_BUILD_RUST=1` only when deliberately building a new backend. Wheels contain
one library and its manifest, tagged `py3-none-<platform>` because ctypes does not
require a specific CPython extension ABI. Source archives include the Rust
sources, MATLAB/Python examples and collected native libraries, allowing
Python-only installation on the included compatible targets. They do not
include compiler caches or local recordings.

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
manylinux image with an isolated Cargo target directory and default target CPU
settings (leave custom `RUSTFLAGS` unset).
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
changes the library, regenerate the packaged checksums, repack the wheel to
refresh `RECORD`, and repeat runtime tests before distributing it. The release
helper deliberately rejects such a change until it has been reviewed. Renaming
a wheel is not a substitute for this audit.

The MATLAB R2026b gateway was compiled separately on Debian 13 with GCC 14.2.
Its imported glibc symbols reach 2.34, and it also requires MATLAB's `libmx.so`
and `libmex.so`. Only its Debian 13/MATLAB R2026b runtime has been verified; the
Python backend's manylinux claim does not extend to the MATLAB gateway.

The [release workflow](../.github/workflows/publish-python-package.yml) packages
existing validated artifacts on each supported OS; it does not recollect them.
For changed Rust code, commit the source first, rebuild/test each target, and
commit the new artifacts before running that workflow. Changes to the MEX C
bridge also require rebuilding every affected MATLAB gateway.

## Standalone Rust

The crate exposes reader, writer and processing APIs, a CLI, and `rlib`, static
library and C-compatible shared-library outputs. Python is not required for
Rust API or CLI use. See `rust/cine-core/include/cine_core.h` for the C ABI and
buffer ownership rules, or generate Rust API documentation:

```sh
cargo doc --workspace --no-deps --open
```
