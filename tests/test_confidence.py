"""Tests for the Confidence Engine v0 (Milestone 9).

Covers low/medium/high risk, the evidence-based rules, and the key differentiator
that the score ignores a model's self-reported confidence. Also checks storage
(confidence_report.json) and the CLI card.
"""

import json
import os
import shutil
from pathlib import Path

import pytest

from ammo import cli
from ammo.adapters import AdapterResponse, Evidence
from ammo.kernel.confidence import ConfidenceEngine, ConfidenceReport
from ammo.kernel.task_understanding import TaskVector
from ammo.kernel.team_formation.execution_plan import ExecutionPlan, TeamMember

REPO_ROOT = Path(__file__).resolve().parents[1]
ENGINE = ConfidenceEngine()


def mk_task(domain="general", risk="low", needs_tests=False, intent="answer"):
    return TaskVector(raw_input="x", domain=domain, intent=intent, risk=risk, needs_tests=needs_tests)


def mk_plan(roles):
    team = [TeamMember(role=r, model=f"m_{r}") for r in roles]
    return ExecutionPlan(selected_system="s", selected_team=team, roles=list(roles),
                         risk_controls=["no_secret_access"])


def mk_resp(role, evidence=None, self_conf=0.99, model=None):
    # self_conf is deliberately high to prove the engine ignores it.
    return AdapterResponse(role=role, model=model or f"m_{role}", output=f"out:{role}",
                           confidence=self_conf, evidence=evidence or [])


# --- risk levels ------------------------------------------------------------

def test_low_risk_band_and_next_action():
    task = mk_task(risk="low")
    plan = mk_plan(["fast_worker"])
    resp = [mk_resp("fast_worker", [Evidence("result", "single-pass result")])]
    report = ENGINE.assess(task, plan, resp, mode="mock")
    assert 0.0 <= report.confidence_score <= 1.0
    assert report.confidence_band in {"medium", "low"}
    assert any("mock adapter only" in r for r in report.reasons_negative)
    assert "real execution" in report.required_next_action


def test_medium_risk_is_flagged():
    task = mk_task(domain="coding", risk="medium", intent="code_review")
    plan = mk_plan(["builder", "critic"])
    resp = [mk_resp("builder", [Evidence("diff", "diff")]),
            mk_resp("critic", [Evidence("review", "0 issues", ok=True)])]
    report = ENGINE.assess(task, plan, resp, mode="mock")
    assert any("medium-risk" in r for r in report.reasons_negative)


def test_high_risk_scores_lower_than_low_risk():
    plan = mk_plan(["fast_worker"])
    resp = [mk_resp("fast_worker", [Evidence("result", "r")])]
    low = ENGINE.assess(mk_task(risk="low"), plan, resp, mode="mock")
    high = ENGINE.assess(mk_task(risk="high"), plan, resp, mode="mock")
    assert high.confidence_score < low.confidence_score
    assert any("high-risk" in r for r in high.reasons_negative)


# --- evidence-based rules ---------------------------------------------------

def test_tests_passed_increases_confidence():
    task = mk_task(domain="coding", risk="low", needs_tests=True, intent="debug_and_patch")
    plan = mk_plan(["builder", "critic"])
    without = [mk_resp("builder", [Evidence("diff", "d")]),
               mk_resp("critic", [Evidence("review", "ok", ok=True)])]
    with_tests = [mk_resp("builder", [Evidence("diff", "d"), Evidence("test_result", "12 passed", ok=True)]),
                  mk_resp("critic", [Evidence("review", "ok", ok=True)])]
    r_without = ENGINE.assess(task, plan, without, mode="mock")
    r_with = ENGINE.assess(task, plan, with_tests, mode="mock")
    assert r_with.confidence_score > r_without.confidence_score
    assert any("tests passed" in r for r in r_with.reasons_positive)
    assert any("no real tests executed" in r for r in r_without.reasons_negative)


def test_unresolved_objection_decreases_confidence():
    task = mk_task(domain="research", risk="low", intent="verify")
    plan = mk_plan(["researcher", "critic"])
    clean = [mk_resp("researcher", [Evidence("sources", "3")]),
             mk_resp("critic", [Evidence("review", "0 issues", ok=True)])]
    objected = [mk_resp("researcher", [Evidence("sources", "3")]),
                mk_resp("critic", [Evidence("review", "2 issues", ok=False)])]
    r_clean = ENGINE.assess(task, plan, clean, mode="mock")
    r_obj = ENGINE.assess(task, plan, objected, mode="mock")
    assert r_obj.confidence_score < r_clean.confidence_score
    assert any("unresolved objection" in r for r in r_obj.reasons_negative)


def test_independent_critic_and_agreement_add_positives():
    task = mk_task(domain="research", risk="low", intent="verify")
    plan = mk_plan(["researcher", "critic"])
    resp = [mk_resp("researcher", [Evidence("sources", "3")], model="m1"),
            mk_resp("critic", [Evidence("review", "ok", ok=True)], model="m2")]
    report = ENGINE.assess(task, plan, resp, mode="mock")
    assert any("independent critic passed" in r for r in report.reasons_positive)
    assert any("agreed" in r for r in report.reasons_positive)


def test_missing_evidence_penalized():
    task = mk_task(risk="low")
    plan = mk_plan(["fast_worker"])
    resp = [mk_resp("fast_worker", evidence=[])]
    report = ENGINE.assess(task, plan, resp, mode="mock")
    assert any("no evidence" in r for r in report.reasons_negative)


# --- the differentiator: ignore model self-confidence -----------------------

def test_score_ignores_model_self_confidence():
    """A worker claiming 0.99 confidence, with no evidence + high risk, is NOT trusted."""
    task = mk_task(risk="high")
    plan = mk_plan(["fast_worker"])
    resp = [mk_resp("fast_worker", evidence=[], self_conf=0.99)]
    report = ENGINE.assess(task, plan, resp, mode="mock")
    assert report.confidence_score <= 0.5  # evidence-based, not self-reported


# --- report shape -----------------------------------------------------------

def test_report_card_format():
    report = ConfidenceReport(0.74, "medium", ["a"], ["b"], "do x")
    card = report.to_card()
    for token in ["Confidence:", "Band:", "Positive:", "Negative:", "Next action:"]:
        assert token in card
    d = report.to_dict()
    assert d["confidence_score"] == 0.74 and d["required_next_action"] == "do x"


# --- CLI + storage ----------------------------------------------------------

@pytest.fixture
def ammo_root(tmp_path, monkeypatch):
    root = tmp_path / "root"
    root.mkdir()
    os.symlink(REPO_ROOT / "registry", root / "registry")
    shutil.copytree(REPO_ROOT / "systems", root / "systems")  # copy: `run` writes role dirs
    for name in ("runtime", "memory", "vaults"):
        (root / name).mkdir()
    monkeypatch.setenv("AMMO_ROOT", str(root))
    return root


def test_cli_run_show_confidence_and_storage(ammo_root, capsys):
    code = cli.main(["run", "--mock", "이 Python repo 수정해줘", "--show-confidence"])
    out = capsys.readouterr().out
    assert code == 0
    for token in ["Confidence:", "Band:", "Positive:", "Negative:", "Next action:"]:
        assert token in out

    run_id = next(l.split("run_id: ", 1)[1].strip() for l in out.splitlines() if l.startswith("run_id: "))
    report_path = ammo_root / "runtime" / "runs" / run_id / "confidence_report.json"
    assert report_path.is_file()
    data = json.loads(report_path.read_text(encoding="utf-8"))
    assert set(data) == {"confidence_score", "confidence_band", "reasons_positive",
                         "reasons_negative", "required_next_action"}


def test_cli_run_stores_confidence_even_without_flag(ammo_root, capsys):
    code = cli.main(["run", "--mock", "오늘 할 일 정리해줘"])
    out = capsys.readouterr().out
    assert code == 0
    run_id = next(l.split("run_id: ", 1)[1].strip() for l in out.splitlines() if l.startswith("run_id: "))
    summary = json.loads(
        (ammo_root / "runtime" / "runs" / run_id / "run_summary.json").read_text(encoding="utf-8")
    )
    assert summary["confidence"] is not None
    assert (ammo_root / "runtime" / "runs" / run_id / "confidence_report.json").is_file()
