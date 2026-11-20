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
| `x86_64-pc-windows-msvc` | Python library, standalone tool and MATLAB R2026b gateway built/tested on Windows x64 |
| `x86_64-unknown-linux-gnu` | Python library and standalone tool built/tested for glibc 2.28+; MATLAB R2026b gateway tested on Debian 13 |

Other architectures require their own builds. Missing targets fail clearly at
installation; no automatic Rust build or download is attempted. Linux binaries
must also match the host's libc requirements. A Debian build is not a substitute
for a manylinux build when preparing broadly compatible PyPI wheels.

The collected Linux x64 Rust library and CLI were built in the pinned
`manylinux_2_28_x86_64` image recorded in their manifest. The Python wheel was
audited and tested on glibc 2.28 and Debian 13. These are glibc builds; Alpine/musl
and Linux ARM64 require separate artifacts. The MATLAB gateway was built on
Debian 13 with MATLAB R2026b and requires MATLAB's libraries; its imported glibc
symbols reach 2.34. Its separate requirements are recorded under
`artifact_requirements` in the manifest. The Python/CLI glibc 2.28 floor does not
apply to the MATLAB gateway.

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

Running the collector natively on a newer Linux distribution replaces the
portable Rust artifacts with a build for that host. For distribution, rebuild
the Rust library and CLI in the intended manylinux container, regenerate their
manifest there, and retain the MATLAB gateway's separate build requirements.
See [Linux portability](../docs/BUILDING.md#linux-portability) before replacing
collected Linux artifacts.

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

MATLAB users run `install_cine_backend` with `Matlab/` on their path. It validates
the selected artifacts and copies the gateway into `Matlab/private/` and its
shared library into `Matlab/private/lib/<MATLAB arch>/`. No Python, Rust or C
compiler is needed. For Windows the architecture is `win64`; Linux x64 uses
`glnxa64`; Apple Silicon uses `maca64`. The installer also recognizes `maci64`,
but an Intel macOS build has not been collected.

Python distributions are built under `dist/release/` by `scripts/release.py`;
see the [release packaging guide](../docs/RELEASING.md).
Reference CINE recordings are test data and must not be added to this directory.
