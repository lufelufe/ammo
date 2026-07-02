"""Tests for the side-effecting-tool sandbox (M: sandbox)."""

import os
import shutil
from pathlib import Path

import pytest

from ammo import cli
from ammo.adapters.contract import ToolRequest
from ammo.tools import PermissionGate, Sandbox, SandboxError, ToolExecutor

REPO_ROOT = Path(__file__).resolve().parents[1]


def _gate(root):
    return PermissionGate(root, read_scopes=["systems/x"], write_scopes=["memory/x"],
                          network=False, allowed_tools={"fs.write", "shell.run", "git"},
                          ammoignore=[])


# --- Sandbox primitive ------------------------------------------------------

def test_sandbox_write_and_read_confined(tmp_path):
    sb = Sandbox(tmp_path / "sb", isolation=None)
    sb.write("a/b.txt", "hi")
    assert sb.read("a/b.txt") == "hi"
    assert sb.files() == ["a/b.txt"]


def test_sandbox_blocks_path_escape(tmp_path):
    sb = Sandbox(tmp_path / "sb", isolation=None)
    with pytest.raises(SandboxError):
        sb.write("../escape.txt", "x")


def test_sandbox_runs_allowlisted_command(tmp_path):
    sb = Sandbox(tmp_path / "sb", isolation=None)
    code, out = sb.run(["echo", "hello"])
    assert code == 0 and "hello" in out


def test_sandbox_refuses_non_allowlisted_command(tmp_path):
    sb = Sandbox(tmp_path / "sb", isolation=None)
    with pytest.raises(SandboxError):
        sb.run(["rm", "-rf", "/"])


def test_sandbox_run_confined_to_its_dir(tmp_path):
    sb = Sandbox(tmp_path / "sb", isolation=None)
    code, out = sb.run(["pwd"])
    assert code == 0 and str(sb.dir) in out


# --- ToolExecutor with sandbox ---------------------------------------------

def test_executor_writes_into_sandbox(tmp_path):
    ex = ToolExecutor(_gate(tmp_path), sandbox=Sandbox(tmp_path / "sb", isolation=None))
    ev = ex.execute(ToolRequest("fs.write",
                                {"path": str(tmp_path / "memory" / "x" / "patch.txt"),
                                 "content": "hello"}))
    assert ev.ok and ev.kind == "fs_write" and "5 bytes" in ev.summary


def test_executor_runs_safe_shell(tmp_path):
    ex = ToolExecutor(_gate(tmp_path), sandbox=Sandbox(tmp_path / "sb", isolation=None))
    ev = ex.execute(ToolRequest("shell.run", {"cmd": "echo ok"}))
    assert ev.ok and ev.kind == "shell" and "exit 0" in ev.summary


def test_executor_blocks_dangerous_shell(tmp_path):
    ex = ToolExecutor(_gate(tmp_path), sandbox=Sandbox(tmp_path / "sb", isolation=None))
    ev = ex.execute(ToolRequest("shell.run", {"cmd": "rm -rf /"}))
    assert not ev.ok and "blocked" in ev.summary


def test_git_still_deferred_even_with_sandbox(tmp_path):
    ex = ToolExecutor(_gate(tmp_path), sandbox=Sandbox(tmp_path / "sb", isolation=None))
    ev = ex.execute(ToolRequest("git", {"op": "diff"}))
    assert ev.ok and "not executed" in ev.detail


def test_denied_tool_never_reaches_sandbox(tmp_path):
    # tool not in permissions -> denied by the gate before any sandbox run
    gate = PermissionGate(tmp_path, read_scopes=[], write_scopes=[], network=False,
                          allowed_tools=set(), ammoignore=[])
    ex = ToolExecutor(gate, sandbox=Sandbox(tmp_path / "sb", isolation=None))
    ev = ex.execute(ToolRequest("shell.run", {"cmd": "echo hi"}))
    assert not ev.ok and "denied" in ev.summary


def test_no_sandbox_defers_side_effects(tmp_path):
    ex = ToolExecutor(_gate(tmp_path))  # no sandbox
    ev = ex.execute(ToolRequest("shell.run", {"cmd": "echo hi"}))
    assert ev.ok and "not executed" in ev.detail


# --- CLI --------------------------------------------------------------------

@pytest.fixture
def ammo_root(tmp_path, monkeypatch):
    root = tmp_path / "root"
    root.mkdir()
    os.symlink(REPO_ROOT / "registry", root / "registry")
    shutil.copytree(REPO_ROOT / "systems", root / "systems")
    for name in ("runtime", "memory", "vaults"):
        (root / name).mkdir()
    monkeypatch.setenv("AMMO_ROOT", str(root))
    return root


def test_cli_run_execute_tools_creates_sandbox(ammo_root, capsys):
    code = cli.main(["run", "--mock", "--execute-tools", "이 python repo 버그 고쳐줘"])
    out = capsys.readouterr().out
    assert code == 0
    assert "sandbox: " in out
    # a sandbox dir was created under runtime/sandbox/
    assert list((ammo_root / "runtime" / "sandbox").iterdir())
