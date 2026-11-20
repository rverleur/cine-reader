"""Validate the exact Git index without modifying the working tree or staging area."""

from __future__ import annotations

import importlib.util
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path


class CheckFailure(RuntimeError):
    """A failed prerequisite or check must stop the commit."""


def git(root: Path, *arguments: str) -> bytes:
    return subprocess.check_output(["git", "-C", str(root), *arguments])


def configuration(root: Path, key: str) -> str | None:
    result = subprocess.run(
        ["git", "-C", str(root), "config", "--local", "--get", key],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode not in (0, 1):
        raise CheckFailure(f"Cannot read local Git setting {key}: {result.stderr.strip()}")
    return result.stdout.strip() or None


def staged_state(root: Path) -> bytes:
    """Index object IDs include content, file modes and merge stages, not mtimes."""
    state = git(root, "ls-files", "--stage", "-z")
    for entry in state.split(b"\0"):
        if not entry:
            continue
        attributes, _ = entry.split(b"\t", 1)
        mode, _, stage = attributes.split()
        if stage != b"0":
            raise CheckFailure("Resolve staged merge conflicts before committing.")
        if mode == b"160000":
            raise CheckFailure(
                "This gate does not export submodules; configure their checks first."
            )
        if mode not in (b"100644", b"100755"):
            raise CheckFailure(
                "Symlinks and special index entries need an explicit isolated-check policy."
            )
    return state


def export_staged(root: Path, destination: Path) -> None:
    """Export raw index blobs, bypassing smudge filters and sparse-checkout flags.

    GIT_INDEX_FILE remains in effect, including Git's index for commit -a/--only.
    """
    destination.mkdir(parents=True, exist_ok=True)
    entries = staged_state(root).split(b"\0")
    with subprocess.Popen(
        ["git", "-C", str(root), "cat-file", "--batch"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
    ) as process:
        assert process.stdin is not None and process.stdout is not None
        try:
            for entry in entries:
                if not entry:
                    continue
                attributes, filename = entry.split(b"\t", 1)
                mode, object_id, _ = attributes.split()
                relative = Path(os.fsdecode(filename))
                if relative.is_absolute() or ".." in relative.parts:
                    raise CheckFailure("Unsafe path in the Git index.")
                target = destination / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                process.stdin.write(object_id + b"\n")
                process.stdin.flush()
                header = process.stdout.readline().split()
                if len(header) != 3 or header[0] != object_id or header[1] != b"blob":
                    raise CheckFailure(f"Cannot export staged blob for {relative}")
                remaining = int(header[2])
                with target.open("wb") as output:
                    while remaining:
                        data = process.stdout.read(min(remaining, 1024 * 1024))
                        if not data:
                            raise CheckFailure(f"Truncated Git object for {relative}")
                        output.write(data)
                        remaining -= len(data)
                if process.stdout.read(1) != b"\n":
                    raise CheckFailure("Invalid Git object stream delimiter.")
                target.chmod(0o755 if mode == b"100755" else 0o644)
        except BaseException:
            process.kill()
            raise
        finally:
            process.stdin.close()
        if process.wait() != 0:
            raise CheckFailure("Git could not export the complete staged snapshot.")


def executable(name: str, override: str | None = None) -> str:
    candidates = [override] if override else [shutil.which(name)]
    if not override:
        if name == "cargo":
            candidates.append(
                str(Path.home() / ".cargo" / "bin" / ("cargo.exe" if os.name == "nt" else "cargo"))
            )
        if sys.platform == "darwin":
            candidates.extend(
                str(Path(folder) / name) for folder in ("/opt/homebrew/bin", "/usr/local/bin")
            )
        if name == "matlab":
            if sys.platform == "darwin":
                candidates.extend(
                    str(path / "bin/matlab")
                    for path in sorted(Path("/Applications").glob("MATLAB_*.app"), reverse=True)
                )
            elif os.name == "nt":
                base = Path(os.environ.get("ProgramFiles", "C:/Program Files")) / "MATLAB"
                candidates.extend(
                    str(path / "bin/matlab.exe") for path in sorted(base.glob("R*"), reverse=True)
                )
    for candidate in candidates:
        if candidate:
            found = shutil.which(candidate)
            if found:
                return str(Path(found).absolute())
    raise CheckFailure(f"Required executable {name!r} was not found. See docs/DEVELOPMENT.md.")


def prepare_environment(root: Path) -> dict[str, str]:
    """Isolate child checks from Git's index/worktree and stale native libraries."""
    environment = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    # Test this machine's build, never a cross-compiled artifact or caller's flags.
    for key in (
        "CARGO_BUILD_TARGET",
        "RUSTFLAGS",
        "CARGO_ENCODED_RUSTFLAGS",
        "PYTHONPATH",
        "PYTHONHOME",
        "PYTEST_ADDOPTS",
        "PYTEST_PLUGINS",
        "CINE_READER_LIBRARY",
    ):
        environment.pop(key, None)
    tools = {
        "CINE_CHECK_CARGO": executable("cargo"),
        "CINE_CHECK_MATLAB": executable(
            "matlab", os.environ.get("CINE_MATLAB") or configuration(root, "cine.matlab")
        ),
        "CINE_CHECK_FFMPEG": executable("ffmpeg"),
        "CINE_CHECK_FFPROBE": executable("ffprobe"),
    }
    environment.update(tools)
    folders = list(dict.fromkeys(str(Path(value).parent) for value in tools.values()))
    environment["PATH"] = os.pathsep.join([*folders, environment.get("PATH", "")])
    environment["CARGO_TARGET_DIR"] = str(root / "target" / "commit-check")
    environment["CINE_CHECK_SNAPSHOT"] = "1"
    environment["PYTHONNOUSERSITE"] = "1"
    # Check all auto-loaded pytest behavior from this repository, not ambient plugins.
    environment["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
    corpus = os.environ.get("CINE_TEST_CORPUS") or configuration(root, "cine.testCorpus")
    if corpus:
        directory = Path(corpus).expanduser().resolve()
        if not directory.is_dir():
            raise CheckFailure(f"Configured CINE_TEST_CORPUS does not exist: {directory}")
        environment["CINE_TEST_CORPUS"] = str(directory)
    if sys.platform == "darwin":
        environment["MACOSX_DEPLOYMENT_TARGET"] = "11.0"
    return environment


def run_staged_checks(root: Path) -> None:
    before = staged_state(root)
    if not before:
        raise CheckFailure("The staging area is empty.")
    environment = prepare_environment(root)
    with tempfile.TemporaryDirectory(prefix="cine-commit-") as folder:
        snapshot = Path(folder)
        export_staged(root, snapshot)
        runner = snapshot / "scripts/check_commit.py"
        if not runner.is_file():
            raise CheckFailure("Stage scripts/check_commit.py before enabling this hook.")
        print("[commit] Checking a clean snapshot of the staged files.", flush=True)
        subprocess.run([sys.executable, str(runner)], cwd=snapshot, env=environment, check=True)
        if staged_state(root) != before:
            raise CheckFailure(
                "The staging area changed during checks. Retry the commit to check the new contents."
            )
    print("[commit] All checks passed; the staged contents are unchanged.", flush=True)


def run(label: str, command: list[str], root: Path, environment: dict[str, str]) -> None:
    print(f"\n[commit] {label}", flush=True)
    started = time.monotonic()
    subprocess.run(command, cwd=root, env=environment, check=True, timeout=900)
    print(f"[commit] Passed in {time.monotonic() - started:.1f}s", flush=True)


def run_checks(root: Path) -> None:
    for module in ("numpy", "pytest", "PIL", "av", "ruff", "miss_hit", "miss_hit_core"):
        if importlib.util.find_spec(module) is None:
            raise CheckFailure(
                f"Missing Python tool {module}. Install the project with its [dev] dependencies."
            )
    environment = dict(os.environ)
    cargo = environment["CINE_CHECK_CARGO"]
    python = sys.executable
    paths = ["python", "scripts", "setup.py"]
    run("Python formatting", [python, "-m", "ruff", "format", "--check", *paths], root, environment)
    run("Python lint", [python, "-m", "ruff", "check", *paths], root, environment)
    run("Rust formatting", [cargo, "fmt", "--all", "--", "--check"], root, environment)
    run(
        "MATLAB formatting",
        [python, "-m", "miss_hit_core.mh_style", "--single", "Matlab"],
        root,
        environment,
    )
    run("MATLAB lint", [python, "-m", "miss_hit.mh_lint", "--single", "Matlab"], root, environment)
    run(
        "Rust Clippy (warnings are errors)",
        [
            cargo,
            "clippy",
            "--workspace",
            "--all-targets",
            "--locked",
            "--offline",
            "--",
            "-D",
            "warnings",
        ],
        root,
        environment,
    )
    run(
        "Rust release build",
        [cargo, "build", "--release", "--workspace", "--locked", "--offline"],
        root,
        environment,
    )
    run("Rust tests", [cargo, "test", "--workspace", "--locked", "--offline"], root, environment)
    name = (
        "cine_core.dll"
        if os.name == "nt"
        else ("libcine_core.dylib" if sys.platform == "darwin" else "libcine_core.so")
    )
    library = Path(environment["CARGO_TARGET_DIR"]) / "release" / name
    if not library.is_file():
        raise CheckFailure(f"The release build did not produce the required library: {library}")
    environment["PYTHONPATH"] = str(root / "python/src")
    environment["CINE_READER_LIBRARY"] = str(library)
    run("Python syntax", [python, "-m", "compileall", "-q", *paths], root, environment)
    run(
        "Python and hook regression tests",
        [python, "-m", "pytest", "python/tests", "scripts/tests", "-q"],
        root,
        environment,
    )
    run(
        "MATLAB Code Analyzer, native build and tests",
        [environment["CINE_CHECK_MATLAB"], "-batch", "addpath('Matlab'); check_commit"],
        root,
        environment,
    )


def main(root: Path) -> int:
    try:
        if os.environ.get("CINE_CHECK_SNAPSHOT") == "1":
            run_checks(root)
        else:
            run_staged_checks(root)
    except (
        CheckFailure,
        subprocess.CalledProcessError,
        subprocess.TimeoutExpired,
        OSError,
    ) as error:
        print(f"\n[commit] BLOCKED: {error}", file=sys.stderr, flush=True)
        print(
            "Fix the failure, run scripts/format_code.py if needed, and stage your edits before retrying.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    PROJECT_ROOT = Path(__file__).resolve().parents[1]
    sys.exit(main(PROJECT_ROOT))
