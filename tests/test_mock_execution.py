"""Tests for mock execution: analyze -> form team -> call adapters (Milestone 7)."""

import json
from pathlib import Path

import pytest

from ammo import cli
from ammo.adapters import AdapterResponse, BaseModelAdapter, MockAdapter
from ammo.kernel.capability_graph import CapabilityGraph
from ammo.kernel.executor import Runner
from ammo.kernel.task_understanding import TaskAnalyzer
from ammo.kernel.team_formation import TeamFormer

REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def graph():
    return CapabilityGraph.from_registry(root=REPO_ROOT)


@pytest.fixture(scope="module")
def analyzer():
    return TaskAnalyzer(systems=[])


def _plan(analyzer, graph, prompt):
    task = analyzer.analyze(prompt)
    return TeamFormer(graph).form(task), task


def _mock_factory(model_id):
    return MockAdapter(model_id)


# --- executor ---------------------------------------------------------------

def test_single_member_execution(analyzer, graph):
    plan, task = _plan(analyzer, graph, "오늘 할 일 정리해줘")
    result = Runner(_mock_factory).run(plan, task)
    assert result.mode == "mock"
    assert len(result.responses) == 1
    assert result.responses[0].role == "fast_worker"
    assert result.final_output
    assert 0.0 <= result.aggregate_confidence <= 1.0


def test_multi_member_execution_matches_plan(analyzer, graph):
    plan, task = _plan(analyzer, graph, "이 Python repo 버그 고치고 테스트 추가해줘")
    result = Runner(_mock_factory).run(plan, task)
    assert [r.role for r in result.responses] == plan.roles
    assert [r.model for r in result.responses] == [m.model for m in plan.selected_team]


def test_execution_is_deterministic(analyzer, graph):
    plan, task = _plan(analyzer, graph, "이 주제 자료 조사하고 근거 검증해줘")
    r1 = Runner(_mock_factory).run(plan, task).to_dict()
    r2 = Runner(_mock_factory).run(plan, task).to_dict()
    assert r1 == r2


def test_context_flows_to_later_members(analyzer, graph):
    """Each member should receive the prior members' outputs as context."""
    seen = []

    class RecordingAdapter(BaseModelAdapter):
        def describe(self):
            return {"id": self.model_id}

        def execute(self, request):
            seen.append(request)
            return AdapterResponse(role=request.role, model=request.model,
                                   output=f"out:{request.role}", confidence=0.5)

    plan, task = _plan(analyzer, graph, "이 Python repo 버그 고치고 테스트 추가해줘")
    Runner(lambda mid: RecordingAdapter(mid)).run(plan, task)

    assert len(seen) == len(plan.selected_team)
    assert seen[0].context == {}                       # first member: no prior context
    assert "planner" in seen[1].context                # builder sees planner's output
    assert seen[1].context["planner"] == "out:planner"


def test_result_to_dict_shape(analyzer, graph):
    plan, task = _plan(analyzer, graph, "오늘 할 일 정리해줘")
    d = Runner(_mock_factory).run(plan, task).to_dict()
    for key in ["task", "mode", "selected_system", "team", "steps",
                "risk_controls", "expected_outputs", "final_output", "aggregate_confidence"]:
        assert key in d


# --- CLI --------------------------------------------------------------------
# (Full `run --mock` + `show-run` CLI coverage lives in test_run_logging.py,
#  which uses a temp AMMO root so runs are not written into the real repo.)

def test_cli_run_without_mock_refuses(monkeypatch, capsys):
    monkeypatch.setenv("AMMO_ROOT", str(REPO_ROOT))
    code = cli.main(["run", "some request"])
    out = capsys.readouterr().out
    assert code == 2
    assert "mock" in out.lower()
