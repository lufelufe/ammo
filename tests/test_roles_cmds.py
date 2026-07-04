"""Tests for the `ammo roles` command UX — the numbered interactive interview."""

import builtins
import os
from pathlib import Path

import pytest

from ammo import cli, roleplan
from ammo.commands import roles_cmds
from ammo.config import load_config

REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def root(tmp_path, monkeypatch):
    r = tmp_path / "root"
    r.mkdir()
    os.symlink(REPO_ROOT / "registry", r / "registry")
    for name in ("runtime", "memory", "vaults", "systems"):
        (r / name).mkdir()
    monkeypatch.setenv("AMMO_ROOT", str(r))
    # keep the interview deterministic + offline: offer all registry models.
    monkeypatch.setattr(roles_cmds, "_usable_models", lambda allow_paid=False: None)
    return r


def test_roles_set_numbered_interview(root, monkeypatch):
    """A number picks the Nth listed candidate; Enter takes the default; '-' skips."""
    plans = {p.slot: p for p in roleplan.plan_roles(root)}
    expect_orch = plans["orchestrator"].candidates[1]["model"]   # answer "2"
    expect_critic = plans["critic"].candidates[0]["model"]       # answer "1"
    expect_worker = plans["worker"].proposed                     # Enter -> default

    answers = iter(["2", "1", "", "-"])   # orch=#2, critic=#1, worker=default, builder=skip
    monkeypatch.setattr(builtins, "input", lambda *_a: next(answers))

    assert cli.main(["roles", "set", "--interactive"]) == 0
    roles = load_config(root).roles
    assert roles["orchestrator"] == expect_orch
    assert roles["critic"] == expect_critic
    assert roles["worker"] == expect_worker
    assert "builder" not in roles           # '-' skipped it
    # orchestrator also anchors the primary seat
    assert load_config(root).primary_model == expect_orch


def test_roles_set_accepts_a_model_id_too(root, monkeypatch):
    """Typing a full id (not a number) still works, for power users / scripts."""
    answers = iter(["claude_a_opus", "-", "-", "-"])
    monkeypatch.setattr(builtins, "input", lambda *_a: next(answers))
    assert cli.main(["roles", "set", "--interactive"]) == 0
    assert load_config(root).roles["orchestrator"] == "claude_a_opus"


def test_roles_set_flags_skip_the_interview(root, monkeypatch):
    """Explicit flags are non-interactive — input() must never be called."""
    def _boom(*_a):
        raise AssertionError("interview should not run when flags are given")
    monkeypatch.setattr(builtins, "input", _boom)
    assert cli.main(["roles", "set", "--orchestrator", "claude_b_fable"]) == 0
    assert load_config(root).roles == {"orchestrator": "claude_b_fable"}
