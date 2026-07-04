"""Tests for the summon workspace step's .ammoignore gate."""

import builtins

import pytest

from ammo.commands import connect_cmds


@pytest.fixture
def pack(tmp_path):
    """A connected-pack layout + a source dir carrying a noise folder + a secret."""
    sysdir = tmp_path / "systems" / "proj"
    sysdir.mkdir(parents=True)
    (sysdir / ".ammoignore").write_text("# commented default\n", encoding="utf-8")
    src = tmp_path / "src"
    src.mkdir()
    (src / "node_modules").mkdir()
    (src / ".env").write_text("SECRET=1", encoding="utf-8")
    return tmp_path, sysdir, src


def _answer(monkeypatch, value):
    monkeypatch.setattr(builtins, "input", lambda *_a: value)


def test_yes_writes_secrets_and_detected_noise(pack, monkeypatch):
    root, sysdir, src = pack
    _answer(monkeypatch, "y")
    connect_cmds._ammoignore_gate(root, "proj", src)
    text = (sysdir / ".ammoignore").read_text(encoding="utf-8")
    assert ".env" in text and "*.key" in text          # always-protected secrets
    assert "node_modules/" in text                      # detected at the top level
    assert "__pycache__/" not in text                   # not present -> not recommended


def test_custom_globs_are_written_verbatim(pack, monkeypatch):
    root, sysdir, src = pack
    _answer(monkeypatch, "build/, *.log")
    connect_cmds._ammoignore_gate(root, "proj", src)
    text = (sysdir / ".ammoignore").read_text(encoding="utf-8")
    assert "build/" in text and "*.log" in text
    assert ".env" not in text                           # custom replaces the recommendation


def test_no_leaves_default(pack, monkeypatch):
    root, sysdir, src = pack
    _answer(monkeypatch, "n")
    connect_cmds._ammoignore_gate(root, "proj", src)
    assert (sysdir / ".ammoignore").read_text(encoding="utf-8") == "# commented default\n"


def test_written_patterns_block_paths_via_permission_gate(pack, monkeypatch):
    """End-to-end: a written pattern makes the permission gate exclude that path."""
    from ammo.tools.permissions import _load_ammoignore, PermissionGate

    root, sysdir, src = pack
    _answer(monkeypatch, "y")
    connect_cmds._ammoignore_gate(root, "proj", src)

    patterns = _load_ammoignore(sysdir)
    gate = PermissionGate(root, read_scopes=[str(src)], write_scopes=[],
                          network=False, allowed_tools=["fs.read"],
                          ammoignore=patterns, source_path=str(src))
    ok = gate.check("fs.read", {"path": str(src / "main.py")})
    blocked = gate.check("fs.read", {"path": str(src / "node_modules" / "x.js")})
    assert ok.allowed is True
    assert blocked.allowed is False and "ammoignore" in blocked.reason
