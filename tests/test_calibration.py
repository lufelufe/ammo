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


def test_rebuild_preserves_feedback_ground_truth(root):
    """`ammo dream --apply` rebuilds aggregates from run rows — a recorded user
    verdict must survive the rebuild, not decay back to the confidence proxy."""
    _seed_run(root, "r-over", 0.8)                 # proxy: success, user: bad
    _seed_run(root, "r-under", 0.3)                # proxy: failure, user: good
    with MemoryStore.open(root) as s:
        s.apply_feedback("r-over", good=False)
        s.apply_feedback("r-under", good=True)
        runs = list(reversed(s.list_runs(limit=50)))
        s.rebuild_aggregates(runs, known_models=["kimi_coder_mock"])
        perf = s.all_model_performance()[0]
        team = s.all_team_synergy()[0]
    # 2 attempts: the good-verdict run counts, the bad-verdict one does not
    assert perf["attempts"] == 2 and perf["successes"] == 1
    assert team["successes"] == 1


def test_best_team_honors_feedback_over_confidence(root):
    _seed_run(root, "r-a", 0.9)                    # high confidence...
    with MemoryStore.open(root) as s:
        s.apply_feedback("r-a", good=False)        # ...but the user says bad
        s.record_run(run_id="r-b", timestamp="2026-07-03", domain="coding", tags=[],
                     selected_system="coding", model_ids=["fast_worker_mock"],
                     team_signature="builder:fast_worker_mock",
                     confidence_score=0.4, user_feedback="good")
        best = s.best_team_for_system("coding")
    # the user-approved team wins over the higher-confidence rejected one
    assert best["team_signature"] == "builder:fast_worker_mock"
    assert best["successes"] == 1


def test_record_run_with_feedback_uses_the_verdict(root):
    with MemoryStore.open(root) as s:
        s.record_run(run_id="r-fb", timestamp="2026-07-03", domain="coding", tags=[],
                     selected_system="coding", model_ids=["kimi_coder_mock"],
                     team_signature="builder:kimi_coder_mock",
                     confidence_score=0.9, user_feedback="bad: hallucinated")
        assert s.all_model_performance()[0]["successes"] == 0


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


# --- learned correction (calibrate --apply -> engine offset) -------------------

def test_calibrate_suggests_negative_offset_for_overconfidence():
    from ammo.kernel.confidence import calibrate

    # 12 runs scored 0.8 ('high' claims >=75% good) but only 25% judged good
    rows = ([{"confidence_score": 0.8, "user_feedback": "good"}] * 3
            + [{"confidence_score": 0.8, "user_feedback": "bad"}] * 9)
    result = calibrate(rows)
    assert result.samples == 12
    assert result.suggested_offset is not None and result.suggested_offset < 0
    high = next(b for b in result.bands if b.band == "high")
    assert high.verdict == "overconfident"


def test_calibrate_needs_ten_samples():
    from ammo.kernel.confidence import calibrate

    rows = [{"confidence_score": 0.8, "user_feedback": "bad"}] * 9
    assert calibrate(rows).suggested_offset is None


def test_engine_applies_the_learned_offset():
    from ammo.adapters import AdapterResponse, Evidence
    from ammo.kernel.confidence import ConfidenceEngine
    from ammo.kernel.task_understanding import TaskVector
    from ammo.kernel.team_formation.execution_plan import ExecutionPlan, TeamMember

    task = TaskVector(raw_input="x", domain="general", intent="answer", risk="low")
    plan = ExecutionPlan(selected_system="s",
                         selected_team=[TeamMember(role="fast_worker", model="m")],
                         roles=["fast_worker"])
    resp = [AdapterResponse(role="fast_worker", model="m", output="out",
                            evidence=[Evidence("result", "r")])]
    plain = ConfidenceEngine().assess(task, plan, resp, mode="mock")
    corrected = ConfidenceEngine(calibration_offset=-0.1).assess(
        task, plan, resp, mode="mock")
    assert corrected.confidence_score == pytest.approx(
        max(0.0, plain.confidence_score - 0.1), abs=0.011)
    assert any("calibration correction -0.10" in r
               for r in corrected.reasons_negative)
    # a hand-edited config cannot inject a wild swing
    wild = ConfidenceEngine(calibration_offset=9.9)
    assert wild._offset == 0.15


def test_positive_offset_cannot_lift_an_unverified_real_run_to_high():
    from ammo.adapters import AdapterResponse, Evidence
    from ammo.kernel.confidence import ConfidenceEngine
    from ammo.kernel.task_understanding import TaskVector
    from ammo.kernel.team_formation.execution_plan import ExecutionPlan, TeamMember

    task = TaskVector(raw_input="x", domain="research", intent="research", risk="low")
    plan = ExecutionPlan(selected_system="s",
                         selected_team=[TeamMember(role="researcher", model="m1"),
                                        TeamMember(role="skeptic", model="m2")],
                         roles=["researcher", "skeptic"])
    resp = [AdapterResponse(role="researcher", model="m1", output="out",
                            evidence=[Evidence("file_read", "read", ok=True)]),
            AdapterResponse(role="skeptic", model="m2", output="ok",
                            evidence=[Evidence("review", "0 issues", ok=True)])]
    report = ConfidenceEngine(calibration_offset=0.15).assess(
        task, plan, resp, mode="real")
    assert report.confidence_band != "high"        # the cap still wins


def test_cli_calibrate_apply_stores_and_run_uses_it(root, monkeypatch, capsys):
    from ammo.config import load_config

    monkeypatch.setenv("AMMO_ROOT", str(root))
    # 12 high-scored runs, mostly judged bad -> negative suggestion
    for i in range(12):
        _seed_run(root, f"cal{i}", 0.8)
    for i in range(12):
        cli.main(["feedback", f"cal{i}", "good" if i < 3 else "bad"])
    capsys.readouterr()

    assert cli.main(["calibrate"]) == 0
    out = capsys.readouterr().out
    assert "suggested correction: -" in out and "--apply" in out

    assert cli.main(["calibrate", "--apply"]) == 0
    out = capsys.readouterr().out
    assert "applied: confidence_offset=-" in out
    offset = load_config(root).confidence_offset
    assert offset < 0

    # a subsequent run's confidence report carries the correction
    import json

    assert cli.main(["run", "--mock", "--no-escalate", "간단한 질문"]) == 0
    out = capsys.readouterr().out
    run_id = next(l.split("run_id: ", 1)[1].strip()
                  for l in out.splitlines() if l.startswith("run_id: "))
    report = json.loads((root / "runtime" / "runs" / run_id /
                         "confidence_report.json").read_text(encoding="utf-8"))
    assert any("calibration correction" in r
               for r in report["reasons_negative"] + report["reasons_positive"])


def test_cli_calibrate_apply_refused_below_min_samples(root, monkeypatch, capsys):
    monkeypatch.setenv("AMMO_ROOT", str(root))
    _seed_run(root, "one", 0.8)
    with MemoryStore.open(root) as s:
        s.apply_feedback("one", good=False)
    assert cli.main(["calibrate", "--apply"]) == 1
    assert "--apply refused" in capsys.readouterr().out
