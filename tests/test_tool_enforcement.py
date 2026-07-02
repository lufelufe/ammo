"""Tests for tool execution + permission enforcement (M: tools)."""

import json
import os
import shutil
from pathlib import Path

import pytest

from ammo import cli
from ammo.adapters.contract import ToolRequest
from ammo.tools import PermissionGate, ToolExecutor

REPO_ROOT = Path(__file__).resolve().parents[1]


def _gate(root, *, read=("systems/x",), write=("memory/x",), network=False,
          tools=("fs.read", "fs.write", "git", "web.search"), ammoignore=()):
    return PermissionGate(root, read_scopes=list(read), write_scopes=list(write),
                          network=network, allowed_tools=set(tools), ammoignore=list(ammoignore))


# --- gate: default-deny + scopes -------------------------------------------

def test_tool_not_permitted_is_denied(tmp_path):
    d = _gate(tmp_path, tools=("fs.read",)).check("shell.run", {})
    assert not d.allowed and "not in permissions" in d.reason


def test_network_denied_when_off(tmp_path):
    assert _gate(tmp_path, network=False).check("web.search", {"q": "x"}).allowed is False
    assert _gate(tmp_path, network=True).check("web.search", {"q": "x"}).allowed is True


def test_path_must_be_in_scope(tmp_path):
    inside = tmp_path / "systems" / "x" / "a.txt"
    d_in = _gate(tmp_path).check("fs.read", {"path": str(inside)})
    d_out = _gate(tmp_path).check("fs.read", {"path": "/etc/hosts"})
    assert d_in.allowed and not d_out.allowed


def test_write_scope_is_separate_from_read(tmp_path):
    # a read-scope path is not writable
    read_only_path = tmp_path / "systems" / "x" / "f.txt"
    assert _gate(tmp_path).check("fs.write", {"path": str(read_only_path)}).allowed is False
    write_path = tmp_path / "memory" / "x" / "f.txt"
    assert _gate(tmp_path).check("fs.write", {"path": str(write_path)}).allowed is True


def test_ammoignore_blocks_path(tmp_path):
    secret = tmp_path / "systems" / "x" / ".env"
    gate = _gate(tmp_path, ammoignore=[".env"])
    assert gate.check("fs.read", {"path": str(secret)}).allowed is False


# --- executor: safe read executes, others gated -----------------------------

def test_executor_reads_in_scope_file(tmp_path):
    f = tmp_path / "systems" / "x" / "readme.txt"
    f.parent.mkdir(parents=True)
    f.write_text("hello", encoding="utf-8")
    ev = ToolExecutor(_gate(tmp_path)).execute(ToolRequest("fs.read", {"path": str(f)}))
    assert ev.ok and ev.kind == "file_read" and "5 bytes" in ev.summary


def test_executor_denies_out_of_scope(tmp_path):
    ev = ToolExecutor(_gate(tmp_path)).execute(ToolRequest("fs.read", {"path": "/etc/hosts"}))
    assert not ev.ok and "denied" in ev.summary


def test_executor_permits_but_defers_side_effecting(tmp_path):
    ev = ToolExecutor(_gate(tmp_path)).execute(ToolRequest("git", {"op": "diff"}))
    assert ev.ok and "not executed" in ev.detail


# --- from_pack --------------------------------------------------------------

def test_from_pack_uses_pack_permissions(tmp_path):
    from ammo.connect import SystemConnector
    from ammo.registry import SystemPackLoader

    root = tmp_path / "root"
    root.mkdir()
    os.symlink(REPO_ROOT / "registry", root / "registry")
    (root / "systems").mkdir()
    SystemConnector(root).new_system("demo")
    pack = SystemPackLoader(root).load("demo")
    gate = PermissionGate.from_pack(root, pack)
    # new_system default tools include fs.read/fs.write; network off
    assert gate.check("web.search", {"q": "x"}).allowed is False


# --- CLI wiring -------------------------------------------------------------

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


def test_cli_run_enforces_and_records_tool_evidence(ammo_root, capsys):
    cli.main(["run", "--mock", "이 python repo 버그 고쳐줘"])
    out = capsys.readouterr().out
    assert "denied (enforced)" in out or "permitted" in out  # enforcement summary line
    run_id = next(l.split("run_id: ", 1)[1].strip() for l in out.splitlines() if l.startswith("run_id: "))

    evidence = json.loads(
        (ammo_root / "runtime" / "runs" / run_id / "evidence.json").read_text(encoding="utf-8")
    )
    tool_ev = [e for e in evidence if e["kind"] in ("tool", "file_read")]
    assert tool_ev  # tool enforcement produced evidence
    # builder's out-of-scope fs.write must be denied
    assert any(e["role"] == "builder" and not e["ok"] and "fs.write" in e["summary"] for e in tool_ev)
