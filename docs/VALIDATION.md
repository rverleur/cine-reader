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
No claim of vendor certification is made. Linux and Intel macOS binaries still
require builds and runtime tests on those platforms. The Windows Python library
and standalone tool have the native validation below; its MATLAB gateway remains
unbuilt. Build guidance is in `docs/BUILDING.md`; a macOS ARM64 wheel and MATLAB
MEX were built locally.

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

MATLAB is not installed on the Windows test machine, so Windows MATLAB compilation
and runtime tests were deliberately deferred. The collected Windows artifacts
are the Rust DLL, standalone executable and checksummed build manifest.

The local commit gate now checks formatting, lint, compilation and tests for
Python, Rust and MATLAB. The GitHub/PyPI publishing workflow and release version
remain deferred; these validation results do not describe the existing PyPI
release.
