"""Tests for user feedback + calibration (ground truth enters the loop)."""

import os
import shutil
from pathlib import Path

import pytest

from ammo import cli
from ammo.memory import MemoryStore

REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def root(tmp_path):
    r = tmp_path / "root"
    r.mkdir()
    os.symlink(REPO_ROOT / "registry", r / "registry")
    shutil.copytree(REPO_ROOT / "systems", r / "systems")
    for name in ("runtime", "memory", "vaults"):
        (r / name).mkdir()
    return r


def _seed_run(root, run_id, confidence):
    with MemoryStore.open(root) as s:
        s.record_run(run_id=run_id, timestamp="2026-07-02", domain="coding", tags=[],
                     selected_system="coding", model_ids=["kimi_coder_mock"],
                     team_signature="builder:kimi_coder_mock",
                     confidence_score=confidence)


def test_bad_feedback_corrects_overcredited_success(root):
    _seed_run(root, "r1", 0.8)                     # proxy counted a success
    with MemoryStore.open(root) as s:
        before = s.all_model_performance()[0]["successes"]
        result = s.apply_feedback("r1", good=False, note="wrong answer")
        after = s.all_model_performance()[0]["successes"]
        team = s.all_team_synergy()[0]["successes"]
    assert before == 1 and after == 0 and team == 0
    assert result["corrected"] == -1
    assert result["feedback"] == "bad: wrong answer"


def test_good_feedback_credits_undercredited_run(root):
    _seed_run(root, "r2", 0.3)                     # proxy counted a failure
    with MemoryStore.open(root) as s:
        result = s.apply_feedback("r2", good=True)
        assert s.all_model_performance()[0]["successes"] == 1
    assert result["corrected"] == 1


def test_agreeing_feedback_changes_nothing(root):
    _seed_run(root, "r3", 0.8)
    with MemoryStore.open(root) as s:
        result = s.apply_feedback("r3", good=True)
        assert s.all_model_performance()[0]["successes"] == 1
    assert result["corrected"] == 0


def test_unknown_run_raises(root):
    _seed_run(root, "r4", 0.8)
    with MemoryStore.open(root) as s:
        with pytest.raises(KeyError):
            s.apply_feedback("nope", good=True)


def test_cli_feedback_and_calibrate(root, monkeypatch, capsys):
    monkeypatch.setenv("AMMO_ROOT", str(root))
    for i, conf in enumerate([0.8, 0.8, 0.3]):
        _seed_run(root, f"c{i}", conf)
    assert cli.main(["feedback", "c0", "good"]) == 0
    assert cli.main(["feedback", "c1", "bad", "--note", "hallucinated"]) == 0
    assert cli.main(["feedback", "c2", "bad"]) == 0
    out = capsys.readouterr().out
    assert "over-credited" in out                  # c1: high conf but bad

    assert cli.main(["calibrate"]) == 0
    out = capsys.readouterr().out
    assert "high" in out and "good-rate=50%" in out            # 1 of 2 high-band good
    assert "OVERCONFIDENT" in out                              # 50% < 0.75 band floor
    assert "collect ~10+" in out


def test_cli_calibrate_without_feedback(root, monkeypatch, capsys):
    monkeypatch.setenv("AMMO_ROOT", str(root))
    _seed_run(root, "x", 0.8)
    assert cli.main(["calibrate"]) == 0
    assert "No feedback recorded yet" in capsys.readouterr().out
