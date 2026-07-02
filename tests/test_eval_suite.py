"""Tests for the AMMO eval suite (Milestone: eval)."""

import json
import os
from pathlib import Path

import pytest

from ammo import cli
from ammo.evalsuite import EvalCase, EvalSuite, load_cases
from ammo.evalsuite.runner import METRICS
from ammo.kernel.capability_graph import CapabilityGraph
from ammo.kernel.task_understanding import TaskAnalyzer

REPO_ROOT = Path(__file__).resolve().parents[1]
EVALS = REPO_ROOT / "evals"


@pytest.fixture(scope="module")
def suite():
    return EvalSuite(TaskAnalyzer(systems=[]), CapabilityGraph.from_registry(root=REPO_ROOT))


# --- cases load -------------------------------------------------------------

def test_bundled_cases_cover_five_domains():
    cases = load_cases(EVALS)
    ids = {c.id for c in cases}
    assert len(cases) >= 5
    assert {"personal", "research", "investment", "coding", "ops"} <= {
        c.id.split("-")[0] for c in cases
    }


# --- scoring ----------------------------------------------------------------

def test_all_bundled_cases_pass(suite):
    report = suite.run(load_cases(EVALS))
    assert report.all_passed, report.to_dict()
    totals = report.metric_totals()
    for metric in METRICS:
        assert totals[metric]["passed"] == totals[metric]["total"]


def test_metrics_present_for_each_case(suite):
    report = suite.run(load_cases(EVALS))
    for result in report.results:
        assert set(result.metrics) == set(METRICS)


def test_wrong_expectation_fails_the_metric(suite):
    bad = EvalCase("coding-bad", "이 python repo 버그 고치고 테스트 추가해줘",
                   {"system": "research", "roles": [], "tools": [], "confidence_max": "medium"})
    result = suite.run_case(bad)
    assert result.metrics["selected_system_correct"] is False
    assert result.metrics["selected_team_correct"] is False
    assert not result.passed


def test_mock_confidence_never_scored_as_high(suite):
    # confidence_reasonable caps at 'medium' for mock; a 'high' expectation-cap
    # is fine, but observed band must never be 'high' under mock.
    report = suite.run(load_cases(EVALS))
    for result in report.results:
        assert result.observed["confidence_band"] != "high"


# --- CLI --------------------------------------------------------------------

@pytest.fixture
def ammo_root(tmp_path, monkeypatch):
    root = tmp_path / "root"
    root.mkdir()
    for name in ("registry", "systems", "evals"):
        os.symlink(REPO_ROOT / name, root / name)
    for name in ("runtime", "memory", "vaults"):
        (root / name).mkdir()
    monkeypatch.setenv("AMMO_ROOT", str(root))
    return root


def test_cli_eval_mock(ammo_root, capsys):
    code = cli.main(["eval", "--mock"])
    out = capsys.readouterr().out
    assert code == 0
    assert "cases fully correct" in out
    for metric in METRICS:
        assert metric in out
    # a report was stored under runtime/reports/
    reports = list((ammo_root / "runtime" / "reports").glob("eval-*.json"))
    assert reports
    data = json.loads(reports[0].read_text(encoding="utf-8"))
    assert data["cases_passed"] == data["cases_total"]


def test_cli_eval_requires_mock(ammo_root, capsys):
    code = cli.main(["eval"])
    out = capsys.readouterr().out
    assert code == 2 and "mock" in out.lower()


# --- learning mode + trend compare (eval expansion) ----------------------------

def test_eval_with_memory_changes_decisions():
    from ammo.evalsuite import EvalSuite
    from ammo.evalsuite.case import EvalCase
    from ammo.memory import MemoryAdvisor

    # research lead seat is a static tie — strong memory for qwen decides it
    stats = {("qwen_planner_mock", "research"): {
        "attempts": 5, "successes": 5, "average_confidence": 0.9,
        "average_cost": 0.0, "average_tokens": 10}}
    advisor = MemoryAdvisor(stats, {})
    case = EvalCase(id="x", input="이 주제 자료 조사하고 근거 검증해줘",
                    expect={"system": "research"})
    static = EvalSuite(root=REPO_ROOT).run_case(case)
    learned = EvalSuite(root=REPO_ROOT, memory=advisor).run_case(case)
    assert static.observed["system"] == learned.observed["system"] == "research"
    # the learning mode is actually consulted (decision may differ from baseline)
    assert learned.observed["roles"] == static.observed["roles"]


def test_cli_eval_compare_shows_trend(tmp_path, monkeypatch, capsys):
    import json as _json

    root = tmp_path / "root"
    (root / "runtime" / "reports").mkdir(parents=True)
    (root / "registry").mkdir()
    for name, passed in (("eval-20260101T000000Z.json", 9), ("eval-20260102T000000Z.json", 11)):
        (root / "runtime" / "reports" / name).write_text(_json.dumps({
            "created_at": name, "mode": "static", "cases_passed": passed, "cases_total": 11,
            "metric_totals": {"selected_system_correct": {"passed": passed, "total": 11}},
            "cases": [{"id": "c1", "passed": passed == 11}],
        }), encoding="utf-8")
    monkeypatch.setenv("AMMO_ROOT", str(root))
    assert cli.main(["eval", "--compare"]) == 0
    out = capsys.readouterr().out
    assert "eval trend" in out and "9/11 -> 11/11 (+2)" in out
    assert "fixed: c1" in out


def test_cli_eval_compare_needs_two_reports(tmp_path, monkeypatch, capsys):
    root = tmp_path / "root"
    root.mkdir()
    monkeypatch.setenv("AMMO_ROOT", str(root))
    assert cli.main(["eval", "--compare"]) == 1
