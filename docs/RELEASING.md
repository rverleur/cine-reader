# Release packaging

Version 0.2.0 packages the already collected backends. Preparing or publishing
Python distributions does not compile Rust and does not require MATLAB. Native
rebuilds are a separate maintainer task in [BUILDING.md](BUILDING.md).

## Version and inputs

The Python version lives in `pyproject.toml`; the prepared release tag is
`v0.2.0`. The `v` prefix matches the versioned documentation links. `PYPI.md` supplies the PyPI page description,
`CHANGELOG.md` supplies release notes, and `LICENSE` is included in each package.
Keep versioned documentation links in `PYPI.md` aligned with the release tag.

Rust's crate version is already 0.2.0. Do not change Rust build inputs merely to
bump a Python release number: their fingerprint ties every collected binary to
its source. Any Rust source/header/Cargo/config change requires rebuilding and
retesting each distributed target before publishing. A MEX bridge C change
requires rebuilding each affected MATLAB gateway as well.

Check `binaries/` for the three complete target directories, each containing its
shared library, CLI, MEX gateway and `build-info.json`. The release helper checks
all artifact sizes/checksums, machine headers and source fingerprints before it
packages anything. MATLAB's separate platform/release requirements remain in
the build manifests and [coverage notes](../binaries/README.md).

## Local packaging and verification

From a development virtual environment with the `dev` dependencies installed:

```sh
python scripts/release.py
python scripts/release_install_check.py
```

The first command copies current source files into a clean temporary build tree,
excluding compiler output, stale package metadata and local recordings. It builds
the host's wheel and a source archive, validates their contents/checksums/tags and
runs Twine's metadata check. Outputs go to `dist/release/`, which must be empty
before a new build. Preserve wanted artifacts or choose another directory.

The second command checks the host wheel, a clean source checkout, and the source
archive when present. It downloads Python dependency wheels, then installs and
runs consumer checks with an empty executable `PATH`, no native-library/compiler
overrides and offline pip build isolation. Reports remain under
`dist/release-checks/`. This catches accidental compiler or media-executable
requirements before distribution.

Both scripts are IDE-friendly: configure their `__main__` blocks. Automation
can use these environment variables:

| Variable | Purpose |
| --- | --- |
| `CINE_RELEASE_OUTPUT` | Distribution directory; default `dist/release` |
| `CINE_RELEASE_SDIST` | `1` builds the source archive; `0` builds only a host wheel |
| `CINE_RELEASE_TAG` | Check a supplied tag against the Python version |
| `CINE_RELEASE_MODE` | `build` (default), or `validate` for the complete four-file release set |
| `CINE_RELEASE_REPORTS` | Consumer-installation report directory |

The local helper packages the current computer's target; it does not manufacture
wheels for other OSes by changing a filename. On Linux, install the auditing tools:

```sh
python -m pip install auditwheel patchelf
```

The helper audits the collected glibc 2.28 backend, repairs its wheel to
`manylinux_2_28_x86_64`, audits again, and checks that the shared library is still
byte-for-byte identical to the verified binary. Unexpected library rewriting or
additional bundled shared libraries fails validation. This audit can run on a
newer glibc host because the committed library was already compiled on 2.28.

## GitHub workflow

`.github/workflows/publish-python-package.yml` uses separate native runner jobs
for Apple Silicon macOS, Windows x64 and Linux x64. Each packages its existing
backend and runs tests and consumer-install checks. Linux additionally audits its
wheel and builds the single source archive. No Rust rebuild occurs in these jobs.

The aggregation job requires exactly these four files for 0.2.0:

```text
cine_handler-0.2.0-py3-none-macosx_11_0_arm64.whl
cine_handler-0.2.0-py3-none-win_amd64.whl
cine_handler-0.2.0-py3-none-manylinux_2_28_x86_64.whl
cine_handler-0.2.0.tar.gz
```

Each wheel contains only the Python package, its matching shared library and
manifest, package metadata and license. The source archive includes the Python,
MATLAB and Rust sources, examples, developer tools and all collected targets.
The CINE reference PDF and private recordings remain outside PyPI distributions.
The repository's GitHub source archive still contains its tracked reference PDF.

A manual `workflow_dispatch` run builds and validates only. It never publishes to
PyPI or attaches release assets. Run this after pushing release preparation and
review the jobs/artifacts before publishing a release. A published prerelease
also builds/tests without uploading to PyPI. A published non-prerelease whose tag
matches the package version runs the PyPI publishing job after all checks pass,
then attaches those same distributions to the GitHub release.

The publishing job uses PyPI Trusted Publishing with the existing `pypi` GitHub
environment and `id-token: write`. The PyPI publisher must match owner `rverleur`,
repository `cine-reader`, workflow `publish-python-package.yml`, and environment
`pypi`. Verify those account-side settings before publishing; committing this
workflow does not configure them. The workflow does not need a PyPI API token.
GitHub environment approvals, if configured, still apply.

Uploading the new distributions updates the PyPI version and renders `PYPI.md`
from their metadata. Creating a GitHub release alone does not change the PyPI
page unless the publish job succeeds. PyPI versions cannot be overwritten; a
post-publication fix needs a new version and rebuilt distributions.

See [PyPI Trusted Publishing](https://docs.pypi.org/trusted-publishers/using-a-publisher/)
for the account-side authentication mechanism. Release creation and publishing
are intentional maintainer actions; local packaging never performs either.
