"""Exercise index isolation and failure gates without invoking external compilers."""

from __future__ import annotations

import importlib.util
import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1]
PROJECT = SCRIPTS.parent


def load_script(name):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


checks = load_script("check_commit")
installer = load_script("install_hooks")


def git(root, *arguments, input=None, check=True):
    return subprocess.run(
        ["git", "-C", str(root), *arguments],
        input=input,
        capture_output=True,
        check=check,
    )


@pytest.fixture
def repository(tmp_path, monkeypatch):
    # These tests can themselves run inside the real snapshot gate. Never inherit
    # its index, worktree, tool paths or corpus configuration in the temporary repo.
    for name in tuple(os.environ):
        if name.startswith(("GIT_", "CINE_CHECK_")) or name in (
            "CINE_MATLAB",
            "CINE_TEST_CORPUS",
        ):
            monkeypatch.delenv(name)
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)
    root = tmp_path / "repository with spaces"
    root.mkdir()
    git(root, "init", "--quiet")
    git(root, "config", "user.name", "Commit gate test")
    git(root, "config", "user.email", "commit-gate@example.invalid")
    git(root, "config", "commit.gpgsign", "false")
    return root


def stage(root, name, content):
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    git(root, "add", "--", name)
    return path


def light_environment(root):
    environment = dict(os.environ)
    for name in tuple(environment):
        if name.startswith("GIT_"):
            environment.pop(name)
    environment["CINE_CHECK_SNAPSHOT"] = "1"
    return environment


def test_snapshot_preserves_staged_binary_and_executable_only(repository, tmp_path):
    tracked = stage(repository, "source with spaces.py", b"staged = True\n")
    binary = bytes(range(256)) + b"\0\xff\0"
    stage(repository, "binary.dat", binary)
    stage(repository, "executable.sh", b"#!/bin/sh\nexit 0\n")
    git(repository, "update-index", "--chmod=+x", "executable.sh")
    tracked.write_bytes(b"unstaged = True\n")
    (repository / "untracked.py").write_text("untracked = True\n")
    before = checks.staged_state(repository)
    snapshot = tmp_path / "snapshot"
    checks.export_staged(repository, snapshot)
    assert (snapshot / tracked.name).read_bytes() == b"staged = True\n"
    assert (snapshot / "binary.dat").read_bytes() == binary
    if os.name != "nt":
        assert (snapshot / "executable.sh").stat().st_mode & 0o111
    assert not (snapshot / "untracked.py").exists()
    assert tracked.read_bytes() == b"unstaged = True\n"
    assert checks.staged_state(repository) == before


def test_alternate_index_is_used_without_touching_default_index(repository, tmp_path, monkeypatch):
    tracked = stage(repository, "value.py", b"default_index = True\n")
    default_state = checks.staged_state(repository)
    alternate = tmp_path / "alternate-index"
    shutil.copyfile(repository / ".git/index", alternate)
    monkeypatch.setenv("GIT_INDEX_FILE", str(alternate))
    tracked.write_bytes(b"alternate_index = True\n")
    git(repository, "add", "value.py")
    alternate_state = checks.staged_state(repository)
    snapshot = tmp_path / "alternate-snapshot"
    checks.export_staged(repository, snapshot)
    assert (snapshot / "value.py").read_bytes() == b"alternate_index = True\n"
    assert alternate_state != default_state
    monkeypatch.delenv("GIT_INDEX_FILE")
    assert checks.staged_state(repository) == default_state


def test_unstaged_attributes_and_smudge_filters_cannot_modify_snapshot(repository, tmp_path):
    stage(repository, ".gitattributes", b"")
    stage(repository, "filtered.txt", b"ORIGINAL\n")
    filter_script = tmp_path / "smudge.py"
    filter_script.write_text(
        "import sys\nsys.stdout.buffer.write(sys.stdin.buffer.read().replace(b'ORIGINAL', b'SMUDGED'))\n"
    )
    git(
        repository,
        "config",
        "filter.inject.smudge",
        shlex.join([sys.executable, str(filter_script)]),
    )
    git(repository, "config", "filter.inject.required", "true")
    (repository / ".gitattributes").write_text("filtered.txt filter=inject\n")
    snapshot = tmp_path / "filtered-snapshot"
    checks.export_staged(repository, snapshot)
    assert (snapshot / "filtered.txt").read_bytes() == b"ORIGINAL\n"
    assert (snapshot / ".gitattributes").read_bytes() == b""


def test_sparse_skip_worktree_file_is_included(repository, tmp_path):
    path = stage(repository, "not-checked-out.py", b"present_in_index = True\n")
    git(repository, "update-index", "--skip-worktree", "not-checked-out.py")
    path.unlink()
    snapshot = tmp_path / "sparse-snapshot"
    checks.export_staged(repository, snapshot)
    assert (snapshot / path.name).read_bytes() == b"present_in_index = True\n"


def test_symbolic_link_index_entry_is_rejected(repository):
    oid = git(
        repository, "hash-object", "-w", "--stdin", input=b"../outside-snapshot"
    ).stdout.strip()
    git(repository, "update-index", "--add", "--cacheinfo", f"120000,{oid.decode()},linked.py")
    with pytest.raises(checks.CheckFailure, match="(?i)symlink|symbolic"):
        checks.staged_state(repository)


def test_unresolved_index_is_rejected(repository):
    oid = git(repository, "hash-object", "-w", "--stdin", input=b"conflicted\n").stdout.strip()
    entries = b"".join(
        b"100644 " + oid + b" " + str(stage).encode() + b"\tconflict.py\n" for stage in (1, 2, 3)
    )
    git(repository, "update-index", "--index-info", input=entries)
    with pytest.raises(checks.CheckFailure, match="merge conflicts"):
        checks.staged_state(repository)


def test_staged_runner_is_required(repository, monkeypatch):
    stage(repository, "only.py", b"value = 1\n")
    monkeypatch.setattr(checks, "prepare_environment", light_environment)
    with pytest.raises(checks.CheckFailure, match="Stage scripts/check_commit.py"):
        checks.run_staged_checks(repository)


def test_index_change_during_checks_blocks_commit(repository, monkeypatch):
    changed = stage(repository, "value.py", b"before = True\n")
    # This child intentionally stages new content while its snapshot is checked.
    # It does not launch compilers or recurse into the commit gate.
    source = (
        "from pathlib import Path\nimport subprocess\n"
        f"Path({str(changed)!r}).write_text('after = True\\n')\n"
        f"subprocess.run(['git', '-C', {str(repository)!r}, 'add', 'value.py'], check=True)\n"
    )
    stage(repository, "scripts/check_commit.py", source.encode())
    monkeypatch.setattr(checks, "prepare_environment", light_environment)
    with pytest.raises(checks.CheckFailure, match="staging area changed"):
        checks.run_staged_checks(repository)


def test_native_artifacts_and_python_imports_are_from_checked_snapshot(tmp_path, monkeypatch):
    snapshot = tmp_path / "snapshot"
    target = tmp_path / "isolated-target"
    name = (
        "cine_core.dll"
        if os.name == "nt"
        else ("libcine_core.dylib" if sys.platform == "darwin" else "libcine_core.so")
    )
    library = target / "release" / name
    library.parent.mkdir(parents=True)
    library.write_bytes(b"test native artifact")
    monkeypatch.setenv("CARGO_TARGET_DIR", str(target))
    monkeypatch.setenv("CINE_CHECK_CARGO", "test-cargo")
    monkeypatch.setenv("CINE_CHECK_MATLAB", "test-matlab")
    monkeypatch.setenv("CINE_READER_LIBRARY", "old-installed-library")
    monkeypatch.setenv("PYTHONPATH", "old-installed-package")
    monkeypatch.setattr(checks.importlib.util, "find_spec", lambda module: object())
    commands = {}

    def capture(label, command, root, environment):
        commands[label] = (command, root, dict(environment))

    monkeypatch.setattr(checks, "run", capture)
    checks.run_checks(snapshot)
    _, checked_root, environment = commands["Python and hook regression tests"]
    assert checked_root == snapshot
    assert environment["PYTHONPATH"] == str(snapshot / "python/src")
    assert environment["CINE_READER_LIBRARY"] == str(library)
    assert "Rust release build" in commands and "Rust tests" in commands
    assert "MATLAB Code Analyzer, native build and tests" in commands


def test_prepare_environment_removes_ambient_git_and_cross_build_settings(repository, monkeypatch):
    monkeypatch.setenv("GIT_INDEX_FILE", "ambient-index")
    monkeypatch.setenv("CARGO_BUILD_TARGET", "different-processor")
    monkeypatch.setenv("RUSTFLAGS", "--cfg unchecked")
    monkeypatch.setenv("PYTEST_ADDOPTS", "--ignore=python/tests")
    monkeypatch.setenv("CINE_READER_LIBRARY", "stale-library")
    monkeypatch.setattr(checks, "executable", lambda name, override=None: str(repository / name))
    environment = checks.prepare_environment(repository)
    for name in (
        "GIT_INDEX_FILE",
        "CARGO_BUILD_TARGET",
        "RUSTFLAGS",
        "PYTEST_ADDOPTS",
        "CINE_READER_LIBRARY",
    ):
        assert name not in environment
    assert environment["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] == "1"


def test_missing_snapshot_library_cannot_fall_back_to_installed_copy(tmp_path, monkeypatch):
    monkeypatch.setenv("CARGO_TARGET_DIR", str(tmp_path / "missing-build"))
    monkeypatch.setenv("CINE_CHECK_CARGO", "test-cargo")
    monkeypatch.setenv("CINE_READER_LIBRARY", str(tmp_path / "installed-library"))
    monkeypatch.setattr(checks.importlib.util, "find_spec", lambda module: object())
    monkeypatch.setattr(checks, "run", lambda *arguments: None)
    with pytest.raises(checks.CheckFailure, match="release build did not produce"):
        checks.run_checks(tmp_path)


def test_installer_preserves_existing_hook_manager(repository):
    git(repository, "config", "core.hooksPath", "existing-hooks")
    with pytest.raises(checks.CheckFailure, match="existing hooks directory"):
        installer.install_hooks(repository, python=sys.executable)
    assert git(repository, "config", "--get", "core.hooksPath").stdout.strip() == b"existing-hooks"


def test_installer_preserves_existing_default_hook(repository):
    hook = repository / ".git/hooks/pre-commit"
    hook.write_text("#!/bin/sh\nexit 7\n")
    with pytest.raises(checks.CheckFailure, match="existing|Existing"):
        installer.install_hooks(repository, python=sys.executable)
    assert hook.read_text() == "#!/bin/sh\nexit 7\n"
    assert git(repository, "config", "--get", "core.hooksPath", check=False).returncode == 1


def test_real_commit_is_blocked_by_staged_runner_and_preserves_index(repository, monkeypatch):
    stage(repository, "value.py", b"value = 1\n")
    git(repository, "commit", "--quiet", "-m", "initial")
    original_head = git(repository, "rev-parse", "HEAD").stdout
    source = (SCRIPTS / "check_commit.py").read_text()
    marker = 'if __name__ == "__main__":'
    assert marker in source
    # Stub only expensive external checks in this isolated copy of the real
    # runner. The index export, subprocess boundary and real Git hook remain live.
    replacement = (
        "def prepare_environment(root):\n"
        "    environment = dict(os.environ)\n"
        "    environment['CINE_CHECK_SNAPSHOT'] = '1'\n"
        "    return environment\n\n"
        "def run_checks(root):\n"
        "    raise CheckFailure('TEST_REQUIRED_CHECK_FAILED')\n\n" + marker
    )
    runner = stage(
        repository, "scripts/check_commit.py", source.replace(marker, replacement).encode()
    )
    # An unstaged "fix" must not let the staged, failing runner pass its checks.
    runner.write_text(
        runner.read_text().replace(
            "raise CheckFailure('TEST_REQUIRED_CHECK_FAILED')",
            "print('UNSTAGED_CHECK_WOULD_PASS')",
        )
    )
    for name in ("pre-commit", "pre-merge-commit", "pre-applypatch"):
        stage(repository, f".githooks/{name}", (PROJECT / ".githooks" / name).read_bytes())
    stage(repository, "value.py", b"value = 2\n")
    monkeypatch.setattr(installer, "executable", lambda name, override=None: sys.executable)
    installer.install_hooks(repository, python=sys.executable)
    before = checks.staged_state(repository)
    result = git(repository, "commit", "-m", "must be blocked", check=False)
    assert result.returncode != 0
    assert b"TEST_REQUIRED_CHECK_FAILED" in result.stderr
    assert b"Checking a clean snapshot" in result.stdout + result.stderr
    assert b"UNSTAGED_CHECK_WOULD_PASS" not in result.stdout + result.stderr
    assert git(repository, "rev-parse", "HEAD").stdout == original_head
    assert checks.staged_state(repository) == before
    assert (repository / "value.py").read_bytes() == b"value = 2\n"
