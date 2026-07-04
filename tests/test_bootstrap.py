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
    save_config(root, AmmoConfig(host="codex", primary_model="codex_gpt5",
                                 models=["codex_gpt5"], default_objective="cost",
                                 configured_at="2026-07-02T00:00:00+00:00"))
    loaded = load_config(root)
    assert loaded.host == "codex" and loaded.default_objective == "cost"
    assert loaded.models == ["codex_gpt5"]


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
    assert config.primary_model == "claude_a_opus"        # host anchors primary
    assert config.primary_provider == "claude-code"
    assert {"claude_a_opus", "claude_b_fable", "claude_a_haiku",
            "claude_a_sonnet", "codex_gpt5"} <= set(config.models)
    assert config.default_objective == "balanced"
    # the workspace grant is pointed to, never auto-applied on a non-interactive summon
    assert "ammo connect" in out
    assert config.roles == {}                              # roles not auto-assigned either
    assert "verify:" in out and "wiring OK" in out         # the mock smoke test ran
    assert not (root / "systems" / "root").exists()


def test_smoke_test_verifies_wiring(root):
    from ammo.bootstrap import smoke_test

    line = smoke_test(root)
    assert "wiring OK" in line and "confidence" in line
    # it records nothing — no run dir, no memory db is created by the probe
    assert not (root / "memory" / "ammo.sqlite").is_file()
    assert not any((root / "runtime" / "runs").glob("*")) if (root / "runtime" / "runs").is_dir() else True


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
    assert config.primary_model == "codex_gpt5"           # new host, new primary


# --- interactive path ------------------------------------------------------------

def test_interactive_answers_flow(root, capsys):
    answers = iter(["y", "claude_a_opus,codex_gpt5", "cost"])
    code = run_start(root, "claude-code", detector=FakeDetector(),
                     interactive=True, ask=lambda _prompt: next(answers))
    assert code == 0
    config = load_config(root)
    assert config.models == ["claude_a_opus", "codex_gpt5"]
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
    assert "codex_gpt5" in flag_team                      # flag overrides config


def test_status_shows_role_setup_step_until_assigned(root):
    # roles unset on an agent host → the summon directs the host to run the
    # card interview.
    save_config(root, AmmoConfig(host="claude-code", primary_model="claude_a_opus"))
    out = build_status(root)
    assert "SETUP STEP" in out
    assert "ammo roles plan --json" in out          # host-directed interview

    # a bare terminal is pointed at the interactive command instead.
    save_config(root, AmmoConfig(host="terminal", primary_model="claude_a_opus"))
    assert "ammo roles set" in build_status(root)

    # once roles exist, the setup step is gone and the assignment is shown.
    save_config(root, AmmoConfig(host="claude-code", primary_model="claude_b_fable",
                                 roles={"orchestrator": "claude_b_fable"}))
    out = build_status(root)
    assert "SETUP STEP" not in out
    assert "orchestrator" in out and "claude-b · fable" in out   # Format A: provider · model


def test_cli_start_and_status(ammo_root, capsys, monkeypatch):
    import ammo.bootstrap as bootstrap

    monkeypatch.setattr(bootstrap, "_detect_statuses",
                        lambda detector=None: FakeDetector().detect_all(DEFAULT_CATALOG))
    assert cli.main(["start", "--host", "claude-code", "--yes"]) == 0
    capsys.readouterr()
    assert cli.main(["status"]) == 0
    assert "primary: claude_a_opus" in capsys.readouterr().out
