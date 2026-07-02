"""Tests for the summon flow — `ammo start` / `ammo status` (M18)."""

import os
import shutil
from pathlib import Path

import pytest

from ammo import cli
from ammo.bootstrap import build_status, detect_host, run_start
from ammo.config import AmmoConfig, load_config, save_config
from ammo.providers import DEFAULT_CATALOG
from ammo.providers.profile import ProviderStatus

REPO_ROOT = Path(__file__).resolve().parents[1]


class FakeDetector:
    """Detector double: claude-code + codex available, nothing else."""

    def detect_all(self, catalog):
        out = []
        for p in catalog:
            available = p.id in {"claude-code", "codex"}
            out.append(ProviderStatus(p, available, "ok" if available else "no",
                                      list(p.models) if available else []))
        return out


@pytest.fixture
def root(tmp_path):
    r = tmp_path / "root"
    r.mkdir()
    os.symlink(REPO_ROOT / "registry", r / "registry")
    shutil.copytree(REPO_ROOT / "systems", r / "systems")
    for name in ("runtime", "memory", "vaults"):
        (r / name).mkdir()
    return r


# --- config -------------------------------------------------------------------

def test_config_roundtrip(root):
    save_config(root, AmmoConfig(host="codex", primary_model="codex_builder",
                                 models=["codex_builder"], default_objective="cost",
                                 configured_at="2026-07-02T00:00:00+00:00"))
    loaded = load_config(root)
    assert loaded.host == "codex" and loaded.default_objective == "cost"
    assert loaded.models == ["codex_builder"]


def test_load_config_missing_returns_none(root):
    assert load_config(root) is None


# --- host detection -------------------------------------------------------------

def test_detect_host_flag_wins():
    assert detect_host("codex", environ={"CLAUDECODE": "1"}) == "codex"


def test_detect_host_env_fingerprints():
    assert detect_host(None, environ={"CLAUDECODE": "1"}) == "claude-code"
    assert detect_host(None, environ={"CODEX_HOME": "/x"}) == "codex"
    assert detect_host(None, environ={}) == "terminal"


# --- first summon (non-interactive) ---------------------------------------------

def test_first_summon_configures_safe_defaults(root, capsys):
    code = run_start(root, "claude-code", detector=FakeDetector(), interactive=False)
    out = capsys.readouterr().out
    assert code == 0
    config = load_config(root)
    assert config.host == "claude-code"
    assert config.primary_model == "claude_a_planner"        # host anchors primary
    assert config.primary_provider == "claude-code"
    assert set(config.models) == {"claude_a_planner", "claude_b_critic", "codex_builder"}
    assert config.default_objective == "balanced"
    # permission-granting steps are pointed to, never auto-applied
    assert "ammo connect" in out and "ammo bind" in out
    assert not (root / "systems" / "root").exists()


def test_repeat_summon_skips_setup(root, capsys):
    run_start(root, "claude-code", detector=FakeDetector(), interactive=False)
    first = load_config(root).configured_at
    capsys.readouterr()
    code = run_start(root, "claude-code", detector=FakeDetector(), interactive=False)
    out = capsys.readouterr().out
    assert code == 0
    assert "first summon setup" not in out and "ready" in out
    assert load_config(root).configured_at == first          # untouched


def test_reconfigure_redoes_setup(root, capsys):
    run_start(root, "claude-code", detector=FakeDetector(), interactive=False)
    code = run_start(root, "codex", detector=FakeDetector(),
                     interactive=False, reconfigure=True)
    assert code == 0
    config = load_config(root)
    assert config.host == "codex"
    assert config.primary_model == "codex_builder"           # new host, new primary


# --- interactive path ------------------------------------------------------------

def test_interactive_answers_flow(root, capsys):
    answers = iter(["y", "claude_a_planner,codex_builder", "cost"])
    code = run_start(root, "claude-code", detector=FakeDetector(),
                     interactive=True, ask=lambda _prompt: next(answers))
    assert code == 0
    config = load_config(root)
    assert config.models == ["claude_a_planner", "codex_builder"]
    assert config.default_objective == "cost"


# --- status ----------------------------------------------------------------------

def test_status_unconfigured(root):
    assert "Not configured" in build_status(root)


def test_status_configured_lists_systems(root):
    run_start(root, "terminal", detector=FakeDetector(), interactive=False)
    text = build_status(root)
    assert "coding" in text and "objective: balanced" in text


# --- objective default from config -----------------------------------------------

@pytest.fixture
def ammo_root(root, monkeypatch):
    monkeypatch.setenv("AMMO_ROOT", str(root))
    return root


def test_configured_objective_drives_plan_team(ammo_root, capsys):
    save_config(ammo_root, AmmoConfig(host="terminal", default_objective="cost"))
    import json

    cli.main(["plan-team", "이 python repo 버그 고쳐줘", "--no-memory"])
    cost_team = {m["model"] for m in json.loads(capsys.readouterr().out)["selected_team"]}
    assert "kimi_coder_mock" in cost_team                    # config default = cost

    cli.main(["plan-team", "이 python repo 버그 고쳐줘", "--no-memory",
              "--optimize", "balanced"])
    flag_team = {m["model"] for m in json.loads(capsys.readouterr().out)["selected_team"]}
    assert "codex_builder" in flag_team                      # flag overrides config


def test_cli_start_and_status(ammo_root, capsys, monkeypatch):
    import ammo.bootstrap as bootstrap

    monkeypatch.setattr(bootstrap, "_detect_statuses",
                        lambda detector=None: FakeDetector().detect_all(DEFAULT_CATALOG))
    assert cli.main(["start", "--host", "claude-code", "--yes"]) == 0
    capsys.readouterr()
    assert cli.main(["status"]) == 0
    assert "primary: claude_a_planner" in capsys.readouterr().out
