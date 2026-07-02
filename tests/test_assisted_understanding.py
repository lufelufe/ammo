"""Tests for model-assisted task understanding (P4): rules first, model fills gaps."""

import json
from pathlib import Path

import pytest

from ammo.kernel.task_understanding import TaskAnalyzer
from ammo.kernel.task_understanding.assist import assisted_analyze, classify

REPO_ROOT = Path(__file__).resolve().parents[1]


def _invoke_returning(payload):
    return lambda prompt: payload


# --- classify: strict parsing, never raises --------------------------------------

def test_classify_parses_valid_json():
    out = classify("x", _invoke_returning(
        'noise {"domain": "research", "intent": "verify_sources", "risk": "low"} tail'))
    assert out == {"domain": "research", "intent": "verify_sources", "risk": "low"}


@pytest.mark.parametrize("payload", [
    "no json at all",
    '{"domain": "cooking"}',                     # unknown domain
    '{"broken json',
    "",
])
def test_classify_rejects_garbage(payload):
    assert classify("x", _invoke_returning(payload)) is None


def test_classify_never_raises_on_invoke_error():
    def boom(prompt):
        raise RuntimeError("provider down")
    assert classify("x", boom) is None


# --- assisted_analyze: policy -----------------------------------------------------

ANALYZER = TaskAnalyzer(systems=[])


def test_confident_rules_never_call_the_model():
    calls = []
    def spy(prompt):
        calls.append(prompt)
        return '{"domain": "personal"}'
    task = assisted_analyze(ANALYZER, "이 python repo 버그 고쳐줘", spy)
    assert task.domain == "coding"                # rules were confident
    assert calls == []                            # zero model calls
    assert task.understanding_source == "rules"


def test_uncertain_rules_adopt_a_valid_hint():
    rules_only = ANALYZER.analyze("asdf qwer zxcv")
    assert rules_only.domain in (None, "general")  # genuinely uncertain
    task = assisted_analyze(ANALYZER, "asdf qwer zxcv", _invoke_returning(
        '{"domain": "research", "intent": "investigate", "risk": "low"}'))
    assert task.domain == "research"              # gap filled
    assert task.understanding_source == "rules+assist"
    assert "research" in (task.candidate_systems or [])  # downstream re-derived


def test_unhelpful_model_leaves_rules_standing():
    task = assisted_analyze(ANALYZER, "asdf qwer zxcv", _invoke_returning("garbage"))
    assert task.understanding_source == "rules"
    task2 = assisted_analyze(ANALYZER, "asdf qwer zxcv",
                             _invoke_returning('{"domain": "general"}'))
    assert task2.understanding_source == "rules"  # 'general' is not a gap-filler


# --- CLI ---------------------------------------------------------------------------

def test_cli_assist_flag(tmp_path, monkeypatch, capsys):
    import os, shutil
    from ammo import cli
    from ammo.commands import common

    root = tmp_path / "root"
    root.mkdir()
    os.symlink(REPO_ROOT / "registry", root / "registry")
    shutil.copytree(REPO_ROOT / "systems", root / "systems")
    for name in ("runtime", "memory", "vaults"):
        (root / name).mkdir()
    monkeypatch.setenv("AMMO_ROOT", str(root))
    monkeypatch.setattr(common, "_assist_invoke", lambda r, a: _invoke_returning(
        '{"domain": "research", "intent": "investigate", "risk": "low"}'))

    code = cli.main(["plan-team", "asdf qwer zxcv", "--assist", "--no-memory"])
    plan = json.loads(capsys.readouterr().out)
    assert code == 0
    assert plan["selected_system"] == "research"   # assist routed the uncertain task


def test_cli_assist_without_provider_notes_and_proceeds(tmp_path, monkeypatch, capsys):
    import os, shutil
    from ammo import cli
    from ammo.commands import common

    root = tmp_path / "root"
    root.mkdir()
    os.symlink(REPO_ROOT / "registry", root / "registry")
    shutil.copytree(REPO_ROOT / "systems", root / "systems")
    for name in ("runtime", "memory", "vaults"):
        (root / name).mkdir()
    monkeypatch.setenv("AMMO_ROOT", str(root))
    monkeypatch.setattr(common, "_assist_invoke", lambda r, a: None)

    code = cli.main(["plan-team", "asdf qwer zxcv", "--assist", "--no-memory"])
    out = capsys.readouterr().out
    assert code == 0
    assert "rules only" in out
