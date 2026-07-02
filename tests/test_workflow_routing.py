"""Tests for pack workflows.yaml stage routing (declared pipelines drive teams)."""

from pathlib import Path

import pytest

from ammo.kernel.capability_graph import CapabilityGraph
from ammo.kernel.task_understanding import TaskAnalyzer
from ammo.kernel.team_formation import TeamFormer

REPO_ROOT = Path(__file__).resolve().parents[1]

BRIEFING_WF = [{"id": "briefing", "stages": [{"role": "analyst"}, {"role": "synthesizer"}],
                "confidence_gate": 0.6}]
INTEL_WF = [{"id": "investment-intel",
             "stages": [{"role": "analyst"}, {"role": "critic"}, {"role": "synthesizer"}],
             "confidence_gate": 0.7}]


@pytest.fixture(scope="module")
def graph():
    return CapabilityGraph.from_registry(root=REPO_ROOT)


@pytest.fixture(scope="module")
def analyzer():
    return TaskAnalyzer(systems=[])


def test_workflow_routes_on_exact_intent_match(graph, analyzer):
    task = analyzer.analyze("오늘 할 일 정리해줘")            # intent: briefing
    plan = TeamFormer(graph, workflows=BRIEFING_WF).form(task)
    assert plan.roles == ["analyst", "synthesizer"]
    assert plan.workflow == "briefing" and plan.workflow_gate == 0.6
    assert "workflow:briefing" in plan.reasoning_summary


def test_hyphenated_id_matches_underscored_intent(graph, analyzer):
    task = analyzer.analyze("포트폴리오 리밸런싱 전략 검토해줘")  # intent: investment_intel
    plan = TeamFormer(graph, workflows=INTEL_WF).form(task)
    assert plan.workflow == "investment-intel"
    assert plan.roles == ["analyst", "critic", "synthesizer"]
    # domain governance survives workflow routing (inherited from the domain template)
    assert "cite_sources" in plan.risk_controls
    assert "no_financial_advice" in plan.risk_controls


def test_no_hijack_without_exact_match(graph, analyzer):
    # a coding task must NOT be routed by an unrelated pack workflow
    task = analyzer.analyze("이 python repo 버그 고쳐줘")
    plan = TeamFormer(graph, workflows=BRIEFING_WF + INTEL_WF).form(task)
    assert plan.workflow is None
    assert plan.roles[0] == "planner"                       # hardcoded template kept


def test_preferences_override_beats_workflow(graph, analyzer):
    task = analyzer.analyze("오늘 할 일 정리해줘")
    plan = TeamFormer(graph, workflows=BRIEFING_WF,
                      preferences={"default_template": "simple_fast"}).form(task)
    assert plan.workflow is None and plan.roles == ["fast_worker"]


def test_unknown_stage_roles_are_skipped(graph, analyzer):
    weird = [{"id": "briefing", "stages": [{"role": "analyst"},
                                           {"role": "not_a_position"}]}]
    task = analyzer.analyze("오늘 할 일 정리해줘")
    plan = TeamFormer(graph, workflows=weird).form(task)
    assert plan.roles == ["analyst"]                        # unknown role dropped


def test_all_unknown_stages_fall_back_to_template(graph, analyzer):
    broken = [{"id": "briefing", "stages": [{"role": "ghost"}]}]
    task = analyzer.analyze("오늘 할 일 정리해줘")
    plan = TeamFormer(graph, workflows=broken).form(task)
    assert plan.workflow is None and plan.roles == ["fast_worker"]
