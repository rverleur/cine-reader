# Changelog

## 0.2.0

- Move CINE I/O, memory management, decoding, writing and pixel processing into a
  dependency-free Rust backend shared by Python, MATLAB and the standalone tool.
- Preserve the existing Python and MATLAB reading APIs while opening lazily and
  decoding frames on demand. Add canonical top-down/RGB reading as an opt-in.
- Write normal and packed10 CINE files from arrays, image sequences and videos,
  including incremental output and disk-spooled unknown-length input.
- Add PyAV video conversion through Python packages, without separate FFmpeg
  programs for ordinary users.
- Include verified native libraries for Apple Silicon macOS, Windows x64 and
  glibc Linux x64. Python wheels, source archives and GitHub checkouts use prebuilt
  libraries without Rust or C toolchains.
- Add a MATLAB-only installer for the collected MEX gateways and shared libraries.
- Expand Python/MATLAB API documentation and runnable feature examples, add the
  MIT license file, and remove obsolete C implementation/build distributions.
- Require staged formatting, linting, compilation and tests before local commits
  after hook installation. Prepare a three-platform wheel publishing workflow.

Packed10 is quantized; RGB packed10 input is sampled into a Bayer mosaic. Direct
PCC acceptance remains unverified. Intel macOS, ARM64 Windows/Linux and musl Linux
need separate native builds. These limitations are detailed in the build and
validation guides.

## 0.1.1

Previous published Python reader package, before the shared Rust backend and
CINE writing features. Historical release artifacts remain available through Git
history and the package/release services rather than as binaries under `release/`.
