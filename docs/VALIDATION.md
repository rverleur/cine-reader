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
- **58 Python tests** pass with the external corpus enabled (44 without it, plus
  14 skipped corpus cases). Source and installed macOS wheel tests were run.
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

## Remaining external checks

The generated files follow the supplied Cine File Format manual and have the
independent checks above. **PCC itself was not available**, so opening/playback in
PCC remains unverified, especially for dimensions unlike a Phantom camera sensor.
No claim of vendor certification is made. Linux, Windows and Intel macOS binaries
also require builds and runtime tests on those platforms. Build guidance is in
`docs/BUILDING.md`; a macOS ARM64 wheel and MATLAB MEX were built locally.

The GitHub/PyPI publishing workflow, release version and future lint/test commit
workflow are intentionally unchanged. Nothing was pushed or published.
