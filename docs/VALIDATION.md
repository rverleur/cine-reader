# Refactor validation (2026-11-19)

Validation used native macOS ARM64, Rust 1.97.1, Python 3.14/NumPy 2.4.4,
MATLAB R2025b and the installed FFmpeg. Release builds use baseline target
instructions, with no GPU or optional CPU feature requirement.

## Supplied camera files

The requested `cine-compressor/examples` directory contains Rust example programs.
Those programs reference `cine-compressor/fixtures/sample_cines`, which contains
the 14 camera files used below. No source recordings were modified.

- The standalone Rust CLI decoded every frame: **37,297 frames**, 29,135,575,868
  source bytes (27.13 GiB). The scan took about 7.9 seconds with a warm OS cache.
- First/middle/last frame SHA-256 hashes match the archived pre-refactor Python
  reader exactly for every file (42 comparisons). The committed reference hashes
  are in `python/tests/data/corpus_reference.json`.
- MATLAB independently opened each file and loaded first/middle/last frames.
- Actual corpus encodings are normal uint16 and packed10, with mono and CFA3.
  Synthetic tests cover the other container depths, packed12, CFA patterns,
  padding, odd sizes, v0 offsets and negative frame numbers.

## Opening performance

Times below are warm-cache medians in milliseconds on this machine, excluding
first native-library initialization. The old constructor decoded the first frame;
the new constructor defers that work until frame access. These figures measure
object creation, not open-plus-first-frame latency. Both retain legacy image APIs.

| File | Frames | Old open ms | Rust-backed open ms |
| --- | ---: | ---: | ---: |
| 45Degree 2.cine | 401 | 0.199 | 0.103 |
| 45Degree 3.cine | 401 | 0.128 | 0.089 |
| 45Degree.cine | 401 | 0.106 | 0.088 |
| Color23CT.cine | 10001 | 3.675 | 0.103 |
| FeNe_knife.cine | 101 | 2.870 | 0.092 |
| FeNe_last_knife_bestfocus.cine | 357 | 2.976 | 0.088 |
| H50 15.cine | 3001 | 2.209 | 0.088 |
| HOLO_spatial.cine | 4278 | 2.004 | 0.086 |
| IPA Laser 5mm 50 ms.cine | 5001 | 1.370 | 0.084 |
| particle1.cine | 351 | 0.899 | 0.090 |
| particle1_HOLO.cine | 501 | 2.556 | 0.084 |
| shot 2.cine | 5001 | 1.038 | 0.084 |
| shot.cine | 5001 | 0.895 | 0.084 |
| visible_0_2500.cine | 2501 | 0.576 | 0.086 |

Warm MATLAB construction measured approximately 0.33–1.03 ms; first class/library
initialization was approximately 128 ms. Explicit close realizes deferred public
state to preserve post-close compatibility. Destruction/reopening discard unused
state without realizing it.

## Writing and sequential reading

A local 64-frame benchmark used 1280×800 images, a known count, and the same input
array reused for each frame. Write timing includes finalization/sync. Read timing
uses Python `load_frame`, no optional repair/demosaic, and a warm filesystem cache.
These short runs describe this machine, not guaranteed disk/CPU throughput.

| Input / encoding | Write frames/s | Read frames/s |
| --- | ---: | ---: |
| mono16 | 1068 | 10318 |
| mono_p10 | 1138 | 3245 |
| rgb8 | 630 | 7814 |
| rgb_p10 | 552 | 3284 |

Known-count writing is sequential. Unknown-count streams add a disk spool and
final copy; they do not retain a video stack in RAM. Reading retains a frame plus
a reusable packed buffer. Explicit mean uses one accumulator; top-k uses bounded
retained samples. Explicit MAD and batch APIs intentionally allocate stacks.

## Correctness and interoperability

- **27 Rust tests** cover decoding, dimensions, malformed/truncated containers,
  ABI overlap/shape checks, annotations, trimming timestamp tags, processing,
  writer metadata, quantization, no-clobber publication, cleanup and ExFAT fallback.
- **73 Python reader/writer tests** pass with the external corpus enabled (59
  without it, plus 14 skipped corpus cases). Commit-hook and packaging tests run
  alongside these in the developer gate.
- **96 randomized processing comparisons** matched the archived Python result
  arrays, including all four Bayer patterns, edge shapes, repair and statistics.
- **12 independent FFmpeg interoperability tests** recover normal mono8/16 and
  RGB24/48 samples exactly at ordinary and odd widths. FFmpeg also recovers the
  exact packed10 codes for mono and Bayer files, including partial final groups.
  FFmpeg expands codes to 16 bits instead of applying the Phantom linearization
  LUT, so packed verification compares the expected code expansion explicitly.
- MATLAB tests cover frame lifecycle, annotations, offsets, metadata post-close,
  mono/RGB round trips, packed10, trimming, processing/statistics, image lists,
  actual video conversion, aborted writes and the supplied corpus.
- Normal16/48 output uses tightly packed sample rows, as described by the CINE
  raw pixel arrays and verified with FFmpeg. Normal8/24 uses DWORD row padding.
  The reader accepts padded and tightly packed normal rows.

## Reproduce

```sh
cargo test --workspace --locked
python -m pytest python/tests -q
# Set CINE_TEST_CORPUS to the external fixtures/sample_cines directory:
CINE_TEST_CORPUS="/path/to/fixtures/sample_cines" cargo test --release --workspace
CINE_TEST_CORPUS="/path/to/fixtures/sample_cines" python -m pytest python/tests -q
target/release/cine-tool verify /path/to/capture.cine
```

In MATLAB run `test_rust_backend(corpus_directory)` after `build_cine_backend`.
The source recordings are not distributed. FFmpeg/Pillow integration tests skip
when their optional dependencies are unavailable.

## Python-only installation

The prebuilt packaging changes were checked on macOS ARM64 using a clean source
snapshot with a collected backend and no local compiler output. With `PATH`
empty and native-library overrides removed, wheel and source-archive builds
succeeded. Eight fresh virtual environments then covered normal source,
editable source, wheel and source-archive installations, both with pip's default
build isolation and with preinstalled Python build dependencies. Dependencies
were installed offline from downloaded wheels.

Every environment passed **30 reader/writer and PyAV tests**, including normal
and packed10 round trips and video conversion. Four environments also passed an
actual Pillow image-file round trip. The legacy external-FFmpeg integration case
was deliberately excluded from these Python-only checks. Installed libraries
resolved inside the corresponding environment (or source tree for editable
installs). The wheel contained only its matching library and manifest; the
source archive retained the collected target directory. No Rust, C compiler,
Git, FFmpeg or FFprobe executable was available to these checks.

**31 packaging regression tests** additionally verify compiler-free selection,
copying and platform tags; invalid manifests, stale sources, corrupted files,
wrong architectures and incompatible system requirements are rejected. Windows
and Linux selection is simulated in these tests; this does not replace native
runtime testing on those platforms.

## Remaining external checks

The generated files follow the supplied Cine File Format manual and have the
independent checks above. **PCC itself was not available**, so opening/playback in
PCC remains unverified, especially for dimensions unlike a Phantom camera sensor.
No claim of vendor certification is made. Intel macOS, Linux ARM64 and musl Linux
still require their own builds and runtime tests. Windows x64 and glibc Linux
x64 validation is recorded below, including their MATLAB R2026b gateways. Build
guidance is in `docs/BUILDING.md`; a macOS ARM64 wheel and MATLAB MEX were built
locally.

## Windows x64 validation

The Windows library and standalone executable were built natively with Rust
1.100.0, Visual Studio 2022 C++ Build Tools and Python 3.13.17. Native validation
passed all **27 Rust tests**, **103 Python/tooling tests**, Python/Rust formatting,
Ruff and Clippy. The Python suite skipped 14 optional corpus cases and one absent
legacy smoke fixture; a separate selected corpus test passed for the transferred
`visible_0_2500.cine` recording.

- The transferred 1,024,510,432-byte recording has SHA256
  `8c551f6afd2050c5c54d606904d85c81aea78c2bc767c776cce6cb34f32749e1`,
  identical to the Mac original. The Windows CLI decoded all **2,501 frames**.
- Frames **0, 1250 and 2500** exactly match the archived reader's raw pixel hashes.
  Raw and demosaiced sample arrays also match the current Mac reader exactly.
- Both platforms exported lossless 16-bit raw PNGs, raw previews and demosaiced
  RGB previews. All nine corresponding PNG pixel arrays match. Display previews
  use a fixed 0–4095 to 0–255 linear scale without white balance or gamma changes;
  the original-depth PNGs preserve decoded samples.
- `dumpbin /DEPENDENTS` reports only Windows system dependencies for the DLL and
  CLI: `KERNEL32.dll`, `ntdll.dll` and `api-ms-win-core-synch-l1-2-0.dll`. Neither
  artifact imports a separate Visual C++ redistributable DLL.
- The Windows wheel and source archive built successfully and passed Twine's
  metadata checks. They remain local validation artifacts, not published releases.
- Fresh Windows environments installed the wheel and a clean checkout with
  `PATH` empty, no compiler/library overrides, offline Python dependency wheels,
  and pip's default build isolation. Each passed **30 writer/PyAV tests**, a
  Pillow image-file round trip and the three reference camera frame comparisons.
  Package and DLL paths were verified inside each isolated environment. Rust,
  Git, C compilers, FFmpeg and FFprobe were unavailable to these consumer checks.

The MATLAB gateway was subsequently built with MATLAB R2026b Update 1 and the
Visual Studio 2022 C compiler. Batch-mode tests over SSH passed the normal and
packed10 round trips, lifecycle, processing, image-list and video-input checks.
MATLAB also opened `visible_0_2500.cine`; its raw arrays for frames 0, 1250 and 2500
exactly match the previously verified Python 16-bit PNG exports.

The collected Windows artifacts now include `cine_mex.mexw64`, the Rust DLL,
standalone executable and checksummed build manifest. The manifest records the
MATLAB release, and the MATLAB companion DLL matches the collected Rust DLL
byte-for-byte.

The local commit gate checks formatting, lint, compilation and tests for Python,
Rust and MATLAB. These results validate the refactored backend; they do not
describe the older 0.1.1 PyPI package. See the release-preparation notes below
for subsequent packaging and documentation checks.

## Linux x64 validation

The Debian 13.5 VM used Python 3.13.5, glibc 2.41, Rust 1.100.0, GCC 14.2 and
MATLAB R2026b Update 1. After native build/test validation, the Rust library and
CLI were rebuilt inside the pinned PyPA `manylinux_2_28_x86_64` container using
glibc 2.28 and baseline CPU instructions. The collected manifest identifies the
image digest, source commit, Rust source fingerprint and artifact checksums.

- All **27 Rust tests** passed in both build environments. The final portable
  library passed **103 Python/tooling tests** on Debian. Fifteen optional cases
  were skipped: the absent legacy smoke recording and 14 unconfigured corpus
  cases. A separate selected corpus test passed for `visible_0_2500.cine`.
- The transferred recording's size and SHA256 match the Windows/Mac reference
  above. The portable CLI decoded all **2,501 frames** on both Debian and the
  glibc 2.28 container.
- Frames **0, 1250 and 2500** exactly match the archived reader's raw hashes and
  the current Mac/Windows raw and demosaiced hashes. Nine PNGs were exported for
  inspection using the same fixed preview scale, retaining original samples in
  the 16-bit raw PNGs.
- The native MATLAB gateway passed reader/writer, lifecycle, processing,
  image-list and video tests using the final portable Rust companion library.
  MATLAB's three reference raw frames exactly match the Python PNGs.
- Auditwheel 6.8.2 confirmed `manylinux_2_28_x86_64` compatibility. Repair changed
  the wheel tags without changing the Rust library bytes or adding shared
  libraries. The packaged manifest's checksums were verified after repair, and
  Twine's metadata check passed.
- Four fresh consumer environments covered both wheel and clean-checkout
  installation on Debian and glibc 2.28/CPython 3.13.18. Each used empty `PATH`,
  no native-library/compiler overrides, offline Python dependency wheels and
  pip's default build isolation. Each passed **30 writer/PyAV tests**, a Pillow
  image-file round trip, and all three reference frame comparisons. The explicit
  external-FFmpeg test was deselected. Installed library paths resolved inside
  each fresh environment and all hashes matched the collected portable backend.

The collected artifacts are `libcine_core.so`, `cine-tool`, `cine_mex.mexa64` and
`build-info.json`. MATLAB's gateway was built on Debian, imports glibc symbols
through 2.34, and needs MATLAB's own libraries; it has not been validated on
older distributions or other MATLAB releases. Its requirements are recorded
separately from the portable Rust backend's glibc 2.28 floor.

The audited wheel and verification images remain local validation artifacts on
the Debian VM. No GitHub release or PyPI upload was made, and the existing Python
version is unchanged pending release preparation.

## 0.2.0 release preparation on macOS

The release preparation changes preserve every collected Rust library, CLI and
MEX byte. All three platform manifests still match their artifact checksums and
the current Rust source fingerprint. Windows/Linux runtime results above remain
applicable to those binaries; the VMs were not needed for this packaging pass.

- Python and MATLAB installation/API guides and feature examples were reviewed
  against the implemented APIs. All six Python examples and all five MATLAB
  examples ran successfully with generated inputs; Python reading/processing
  also used the reference camera recording.
- The new MATLAB-only installer passed in a fresh temporary checkout without
  local native build output and with `PATH` empty. The installed prebuilt backend
  passed MATLAB's full synthetic reader/writer tests. Validation rejects stale
  source, same-size binary corruption, missing gateways and incompatible ABIs;
  CRLF-normalized sources and paths containing shell metacharacters also passed.
  Native installer execution in this pass covered macOS R2025b. The new Windows
  and Linux installer branches have not been executed on their powered-off VMs.
- The full staged commit gate passed Python/Rust/MATLAB formatting, linting,
  compilation and tests, including the configured 14-file camera corpus.
  Separate release-validator regression tests cover all three target manifests,
  corrupted or relabeled wheels, incomplete release sets, licenses, `RECORD`
  checksums and stale source archives. Their fixtures permit committing new Rust
  source before recollecting binaries; actual release validation still rejects
  stale binaries.
- The 0.2.0 Mac wheel and source archive passed Twine metadata checks and archive
  validation. The wheel has only its matching backend and manifest; the source
  archive preserves every collected target and all three language interfaces,
  while excluding private recordings and stale compiler/build output.
- Fresh wheel, checkout and source-archive installations each passed **45 Python
  tests** with `PATH` empty, offline Python dependencies and default pip build
  isolation. Their 28 expected skips cover unavailable external recordings and
  external FFmpeg executables. Additional fresh installations each passed
  **30 writer/PyAV tests**, a Pillow image-file round trip and exact archived
  camera frame hashes at frames 0, 1250 and 2500. Installed library paths and
  SHA256 checks were verified inside each fresh environment.
- The GitHub workflow passed local actionlint validation. Its hosted three-OS
  build/test run remains to be performed after pushing; a manual run builds
  artifacts without publishing. No GitHub release or PyPI upload was performed
  during this preparation.
