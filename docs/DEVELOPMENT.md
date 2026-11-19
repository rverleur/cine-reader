# Commit checks

Every normal commit in an installed clone must pass the checks below. The hook
checks **the staged snapshot**, including partially staged files, rather than
whatever happens to be in the working tree. Unstaged and untracked files are not
included. It refuses to commit if the index changes while checks are running.
Raw Git blobs are exported without checkout/smudge filters, including files
omitted from a sparse working tree. Symlinks and submodules are rejected until
their external dependencies have an explicit isolated-check policy.

| Language | Required checks |
| --- | --- |
| Python | Ruff formatting and lint, syntax compilation, pytest |
| Rust | rustfmt, Clippy with warnings denied, release compilation, cargo tests |
| MATLAB | MISS_HIT formatting and lint, MATLAB Code Analyzer, Rust/MEX build, native tests |

Python tests use the freshly compiled Rust library and the staged Python package.
MATLAB builds its MEX adapter against that same staged Rust source. Builds use a
separate `target/commit-check` cache; no generated library is copied into working
source files. Formatters run in check mode and never rewrite or stage files during
a commit. A missing tool, license failure, test failure, lint warning or formatting
violation stops the commit.

## Install once per clone

Use a Python virtual environment and install the development dependencies:

```sh
python -m pip install -e '.[dev]'
rustup component add rustfmt clippy
python scripts/install_hooks.py
```

The installer sets **local** `core.hooksPath=.githooks` and records the Python and
MATLAB executables for Git clients/IDEs. It does not change global Git settings,
replace another hook manager, or install tools automatically during commits.
Git does not activate repository-provided hooks automatically in a new clone;
run the installer there too. Re-run it if the virtual environment moves.

Required external tools are Rust/Cargo with rustfmt and Clippy, FFmpeg and FFprobe,
and a licensed MATLAB installation with a configured C MEX compiler. Configure
that compiler once with `mex -setup C` in MATLAB. Ruff and MISS_HIT versions are
pinned in the `dev` extra; NumPy, pytest and Pillow are installed with it. Native
MATLAB checks are required even when a commit only changes another language,
because all three interfaces share a backend. A host without MATLAB cannot run
this complete local gate; there is no silent success/skip mode.

The installer discovers MATLAB on PATH, in `/Applications` on macOS, or in
`Program Files/MATLAB` on Windows. Set `MATLAB` in the script's `__main__` block
for a custom installation, or configure the installed clone explicitly:

```sh
git config --local cine.matlab '/full/path/to/matlab'
```

On Windows use `.venv\Scripts\python.exe` instead of an activated `python` if
preferred. Git for Windows runs the small POSIX hook launchers. Their LF endings
are enforced by `.gitattributes`.

## Normal development

```sh
python scripts/format_code.py
# Review the resulting diff, then stage the files/hunks you intend to commit.
git add <files>
git commit -m 'Describe the change'
```

`format_code.py` applies safe Ruff fixes, Ruff formatting, rustfmt and the
MISS_HIT formatter to working files. It does not add files to the index. Remaining
lint findings need a manual correction. Existing public MATLAB names are
preserved by the style configuration.

To run the full gate without making a commit:

```sh
python scripts/check_commit.py
```

This checks staged content too, so **stage fixes before retrying**. A clean
working file with a broken staged version correctly fails. An unstaged syntax
error in a file whose staged version is valid does not contaminate the commit.
The installer also covers automatic merge commits and `git am` through
`pre-merge-commit` and `pre-applypatch`.

Examples and personal scripts are formatted/linted and syntax-checked, but are
not executed against hard-coded private data. The test suites exercise the
reader/writer APIs with generated files, image/video inputs and malformed input.
The optional sample-file test skips when its untracked fixture is absent.

## External camera corpus

The 14 reference recordings are not committed or distributed. Enable their
additional Python, Rust and MATLAB checks by setting `CINE_TEST_CORPUS`, or by
recording the path once in this clone:

```sh
git config --local cine.testCorpus '/path/to/cine-compressor/fixtures/sample_cines'
```

A configured but missing directory fails the gate. An unconfigured corpus is
reported as skipped by its optional tests. This machine's clone is configured
with the supplied sample directory. Clear that local setting when moving to a
machine without the recordings, or configure its corresponding path there.

## Scope and limitations

Local hooks protect normal development commits, but Git deliberately permits
bypassing hooks (for example `--no-verify`) and does not run them for every history
rewriting operation. Server-side required checks/branch protection are a separate
GitHub step. No GitHub publishing, package version or PyPI release workflow is
changed here.

Tool references: [Git hooks](https://git-scm.com/docs/githooks),
[Ruff formatter](https://docs.astral.sh/ruff/formatter/),
[MISS_HIT style checker](https://florianschanda.github.io/miss_hit/style_checker.html).
