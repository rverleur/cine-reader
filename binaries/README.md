# Prebuilt native backends

This directory holds finished native binaries in Git so Python users can use a
checkout or source archive without a Rust compiler. Wheel installations contain
only their matching backend. Compiler caches, local package-library copies and
temporary wheel outputs remain ignored.

Each target directory contains:

- The shared library: `cine_core.dll`, `libcine_core.dylib`, or `libcine_core.so`.
- The standalone `cine-tool.exe` or `cine-tool` executable.
- A `cine_mex.<platform>` gateway when MATLAB was included in the build.
- `build-info.json`, recording the target, ABI, Rust source fingerprint, source
  commit, toolchain, system compatibility and artifact sizes/SHA256 checksums.

## Coverage

| Target | Current validation |
| --- | --- |
| `aarch64-apple-darwin` | Built and tested on the maintainer's Apple Silicon Mac |
| `x86_64-apple-darwin` | Not yet collected or tested |
| `x86_64-pc-windows-msvc` | Python library and standalone tool built/tested on Windows x64; MATLAB gateway not included |
| `x86_64-unknown-linux-gnu` | Awaiting Linux build and tests |

Other architectures require their own builds. Missing targets fail clearly at
installation; no automatic Rust build or download is attempted. Linux binaries
must also match the host's libc requirements. A Debian build is not a substitute
for a manylinux build when preparing broadly compatible PyPI wheels.

## Collection for maintainers

After committing source changes, build/test with the normal developer toolchain
and run the collector using the project virtual environment:

```sh
python scripts/collect_binaries.py
```

Its options are in its `if __name__ == "__main__"` block for IDE execution. It
builds a fresh release backend, and by default also builds and tests the MATLAB
gateway. Source inputs must be clean so `source_commit` identifies a committed
build. Existing collected binaries may be replaced without changing source.

Review and commit only the directory for the target just built, after its native
tests have passed. Example for Windows:

```powershell
git add -- binaries/x86_64-pc-windows-msvc
git diff --cached --stat
git commit -m "build: add verified Windows x64 binaries"
```

The artifact commit naturally follows its source commit; the recorded source
fingerprint identifies the actual Rust inputs. Python installers reject missing,
stale, mismatched, or corrupted artifacts. A new Rust change requires recollecting
each target before distributing that revision to users.

When consuming the MATLAB artifacts directly, copy the gateway into
`Matlab/private/` and its shared library into `Matlab/private/lib/<MATLAB arch>/`.
For Windows the architecture is `win64`; Linux x64 uses `glnxa64`; Apple Silicon
uses `maca64`; Intel macOS uses `maci64`.

Python wheels remain under `dist/` until versioning and release preparation.
Reference CINE recordings are test data and must not be added to this directory.
