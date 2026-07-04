"""Tests for the `ammo roles` command UX — the engine → model → role gate flow."""

import builtins
import os
from pathlib import Path

import pytest

from ammo import cli, roleplan
from ammo.config import load_config
from ammo.providers import DEFAULT_CATALOG
from ammo.providers.profile import ProviderStatus

REPO_ROOT = Path(__file__).resolve().parents[1]

_READY = {"claude-code", "claude-code-b", "codex"}   # ollama intentionally not ready


def _fake_statuses():
    out = []
    for p in DEFAULT_CATALOG:
        avail = p.id in _READY
        out.append(ProviderStatus(p, avail, "authenticated" if avail else "not installed",
                                  list(p.models) if avail else []))
    return out


@pytest.fixture
def root(tmp_path, monkeypatch):
    r = tmp_path / "root"
    r.mkdir()
    os.symlink(REPO_ROOT / "registry", r / "registry")
    for name in ("runtime", "memory", "vaults", "systems"):
        (r / name).mkdir()
    monkeypatch.setenv("AMMO_ROOT", str(r))
    monkeypatch.setattr(roleplan, "_detect_statuses", _fake_statuses)
    return r


def _answers(monkeypatch, seq):
    it = iter(seq)
    monkeypatch.setattr(builtins, "input", lambda *_a: next(it))


def test_engine_model_role_gates(root, monkeypatch):
    """Pick engine, then a model within it, then the role it plays — per member."""
    engines = {e["id"]: e for e in roleplan.team_engines(root)}
    claude_a_models = [n.id for n in engines["claude-a"]["models"]]
    codex_models = [n.id for n in engines["codex"]["models"]]

    # engine #1 (claude-a) → model #1 → role #2 (critic);
    # engine #3 (codex)    → model #1 → role #4 (builder); then done.
    _answers(monkeypatch, ["1", "1", "2", "3", "1", "4", "done"])
    assert cli.main(["roles", "set", "--interactive"]) == 0

    roles = load_config(root).roles
    assert roles["critic"] == claude_a_models[0]
    assert roles["builder"] == codex_models[0]
    # orchestrator/worker were never chosen
    assert "orchestrator" not in roles and "worker" not in roles


def test_not_ready_engine_hits_the_resolve_gate(root, monkeypatch, capsys):
    """Choosing a not-ready engine shows how to fix it and does not proceed."""
    # engine #4 is Local·Ollama (not ready) → resolve gate → then claude-a path.
    _answers(monkeypatch, ["4", "1", "1", "1", "done"])
    assert cli.main(["roles", "set", "--interactive"]) == 0
    out = capsys.readouterr().out
    assert "isn't ready" in out and "ollama" in out.lower()
    # after resolving/choosing a ready engine, the assignment still lands
    assert load_config(root).roles.get("orchestrator")


def test_flags_bypass_the_gate_interview(root, monkeypatch):
    """Explicit flags are non-interactive — no gate prompts run."""
    def _boom(*_a):
        raise AssertionError("interview should not run when flags are given")
    monkeypatch.setattr(builtins, "input", _boom)
    assert cli.main(["roles", "set", "--orchestrator", "claude_b_fable"]) == 0
    assert load_config(root).roles == {"orchestrator": "claude_b_fable"}
