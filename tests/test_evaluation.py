"""Tests for system-level evaluation (Milestone 13)."""

import os
import shutil
from datetime import datetime, timezone
from pathlib import Path

import pytest

from ammo import cli
from ammo.connect import SystemConnector
from ammo.kernel.evaluation import EvaluationEngine, EvaluationReport
from ammo.memory import MemoryStore

REPO_ROOT = Path(__file__).resolve().parents[1]
ENGINE = EvaluationEngine()
NOW = datetime(2026, 7, 1, tzinfo=timezone.utc).isoformat()


@pytest.fixture
def root(tmp_path):
    r = tmp_path / "root"
    r.mkdir()
    os.symlink(REPO_ROOT / "registry", r / "registry")
    shutil.copytree(REPO_ROOT / "systems", r / "systems")  # bring in built-in packs
    for name in ("runtime", "memory", "vaults"):
        (r / name).mkdir()
    return r


# --- evaluation logic -------------------------------------------------------

def test_fully_specced_but_unproven(root):
    SystemConnector(root).new_system("demo")
    report = ENGINE.evaluate(root, "demo")
    assert report.health == "unproven"       # valid + specced, but no runs
    assert "contract valid" in report.works
    assert any("preferences.yaml defined" in w for w in report.works)
    assert any("no runs recorded" in i for i in report.improvements)
    assert report.problems == []


def test_missing_specs_become_improvements(root):
    # built-in pack has no optional specs
    report = ENGINE.evaluate(root, "personal")
    assert any("add preferences.yaml" in i for i in report.improvements)
    assert any("add verification.yaml" in i for i in report.improvements)


def test_unknown_system_is_at_risk(root):
    report = ENGINE.evaluate(root, "ghost")
    assert report.health == "at_risk"
    assert any("contract invalid" in p for p in report.problems)


def test_preferred_capability_gap_is_a_problem(root):
    SystemConnector(root).new_system("demo")
    prefs = root / "systems" / "demo" / ".ammo" / "preferences.yaml"
    prefs.write_text(
        "apiVersion: ammo/v1\nkind: Preferences\nsystem: demo\n"
        "preferred_capabilities: [teleportation]\n",  # no model provides this
        encoding="utf-8",
    )
    report = ENGINE.evaluate(root, "demo")
    assert any("teleportation" in p for p in report.problems)
    assert report.health == "at_risk"


def test_run_history_makes_it_healthy(root):
    SystemConnector(root).new_system("demo")
    with MemoryStore.open(root) as mem:
        for i in range(3):
            mem.record_run(run_id=f"r{i}", timestamp=NOW, domain="general", tags=[],
                           selected_system="demo", model_ids=["m"],
                           team_signature="a", confidence_score=0.8)
    report = ENGINE.evaluate(root, "demo")
    assert report.stats["runs"] == 3
    assert report.stats["success_rate"] == 1.0
    assert report.health == "healthy"


def test_low_confidence_history_suggests_improvement(root):
    SystemConnector(root).new_system("demo")
    with MemoryStore.open(root) as mem:
        for i in range(3):
            mem.record_run(run_id=f"r{i}", timestamp=NOW, domain="general", tags=[],
                           selected_system="demo", model_ids=["m"],
                           team_signature="a", confidence_score=0.3)
    report = ENGINE.evaluate(root, "demo")
    assert any("below gate" in i for i in report.improvements)
    assert report.health == "ok"


def test_report_card_and_dict():
    report = EvaluationReport("x", "healthy", ["w"], ["i"], [], {"runs": 1})
    card = report.to_card()
    for token in ["System:", "Health:", "Works:", "Improvements:", "Problems:"]:
        assert token in card
    assert report.to_dict()["health"] == "healthy"


# --- CLI --------------------------------------------------------------------

@pytest.fixture
def ammo_root(root, monkeypatch):
    monkeypatch.setenv("AMMO_ROOT", str(root))
    return root


def test_cli_eval_system(ammo_root, capsys):
    SystemConnector(ammo_root).new_system("demo")
    code = cli.main(["eval-system", "demo"])
    out = capsys.readouterr().out
    assert code == 0
    assert "System: demo" in out and "Health:" in out


def test_cli_eval_systems_lists_all(ammo_root, capsys):
    code = cli.main(["eval-systems"])
    out = capsys.readouterr().out
    assert code == 0
    for system_id in ("personal", "research", "coding", "ops"):
        assert system_id in out


def test_recurring_negative_reasons_become_suggestions(tmp_path):
    import os, shutil
    root = tmp_path / "root"
    root.mkdir()
    os.symlink(REPO_ROOT / "registry", root / "registry")
    shutil.copytree(REPO_ROOT / "systems", root / "systems")
    for name in ("runtime", "memory", "vaults"):
        (root / name).mkdir()

    from ammo.memory import MemoryStore

    with MemoryStore.open(root) as store:
        for i in range(4):
            store.record_run(
                run_id=f"r{i}", timestamp=f"t{i}", domain="coding", tags=[],
                selected_system="coding", model_ids=["kimi_coder_mock"],
                team_signature="builder:kimi_coder_mock", confidence_score=0.3,
                negative_reasons=["no real tests executed", f"one-off {i}"],
            )
    report = EvaluationEngine().evaluate(root, "coding")
    recurring = [s for s in report.improvements if "recurring issue" in s]
    assert any("no real tests executed" in s and "4/4" in s for s in recurring)
    assert not any("one-off" in s for s in recurring)   # singletons don't recur
