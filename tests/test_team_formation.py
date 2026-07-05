"""Tests for Dynamic Team Formation v0 (Milestone 6).

Covers personal, research, investment, coding, and ops. Uses the real capability
graph and deterministic task analysis. Nothing is executed.
"""

import json
from pathlib import Path

import pytest

from ammo import cli
from ammo.kernel.capability_graph import CapabilityGraph
from ammo.kernel.task_understanding import TaskAnalyzer
from ammo.kernel.team_formation import TeamFormer, form_team

REPO_ROOT = Path(__file__).resolve().parents[1]

def _valid_models():
    # derive from the registry + fixed infra ids so new model nodes don't
    # invalidate the invariant (the point is "no invented ids", not a frozen set)
    from ammo.kernel.team_formation import templates as tpl

    graph = CapabilityGraph.from_registry(root=REPO_ROOT)
    return {n.id for n in graph.nodes} | set(tpl.FIXED_MODELS.values())


VALID_MODELS = _valid_models()


@pytest.fixture(scope="module")
def graph():
    return CapabilityGraph.from_registry(root=REPO_ROOT)


@pytest.fixture(scope="module")
def analyzer():
    return TaskAnalyzer(systems=[])


def _plan(analyzer, graph, prompt):
    return form_team(analyzer.analyze(prompt), graph)


# --- coding: matches the milestone's expected example ----------------------

def test_high_risk_coding_team(analyzer, graph):
    plan = _plan(analyzer, graph, "이 Python repo 버그 고치고 테스트 추가해줘")
    assert plan.selected_system == "coding"
    # fable is the most capable family model, so BOTH account engines field it:
    # the diversity rule splits the A/B fable twins across planner and critic.
    assert [(m.role, m.model) for m in plan.selected_team] == [
        ("planner", "claude_a_fable"),
        ("builder", "codex_gpt5"),
        ("critic", "claude_b_fable"),
        ("test_runner", "local_test_runner"),
    ]
    assert plan.risk_controls == ["require_tests", "diff_review", "no_secret_access"]
    assert plan.expected_outputs == ["code_diff", "test_results"]


# --- research ---------------------------------------------------------------

def test_research_team(analyzer, graph):
    plan = _plan(analyzer, graph, "이 주제 자료 조사하고 근거 검증해줘")
    assert plan.selected_system == "research"
    assert plan.roles == ["researcher", "skeptic", "synthesizer"]
    assert "cite_sources" in plan.risk_controls
    assert "adversarial_check" in plan.risk_controls
    assert plan.expected_outputs == ["report", "citations"]


# --- investment -------------------------------------------------------------

def test_investment_research_team(analyzer, graph):
    plan = _plan(analyzer, graph, "NVDA 투자 분석 리포트 만들어줘")
    assert plan.selected_system == "personal"  # investment served by personal pack
    assert plan.roles == ["researcher", "critic", "judge"]
    assert "verdict" in plan.expected_outputs
    assert "no_financial_advice" in plan.risk_controls


# --- ops --------------------------------------------------------------------

def test_ops_incident_team(analyzer, graph):
    plan = _plan(analyzer, graph, "서버 배포하다가 장애났어 롤백해줘")
    assert plan.selected_system == "ops"
    assert plan.roles == ["triage", "operator", "rollback_critic"]
    assert "rollback_plan" in plan.risk_controls
    assert plan.expected_outputs == ["incident_report", "remediation_actions"]


# --- personal ---------------------------------------------------------------

def test_personal_simple_task_uses_fast_worker(analyzer, graph):
    plan = _plan(analyzer, graph, "오늘 할 일 정리해줘")
    assert plan.selected_system == "personal"
    assert plan.roles == ["fast_worker"]
    # behavior, not identity: the single-worker seat must be cheap AND fast
    node = next(n for n in graph.nodes if n.id == plan.selected_team[0].model)
    assert node.cost_class == "cheap" and node.latency_class == "fast"


# --- cross-cutting invariants ----------------------------------------------

@pytest.mark.parametrize(
    "prompt",
    [
        "이 Python repo 버그 고치고 테스트 추가해줘",
        "이 주제 자료 조사하고 근거 검증해줘",
        "NVDA 투자 분석 리포트 만들어줘",
        "서버 배포하다가 장애났어 롤백해줘",
        "오늘 할 일 정리해줘",
    ],
)
def test_plan_invariants(analyzer, graph, prompt):
    plan = _plan(analyzer, graph, prompt)
    # every assigned model is a real graph node or a known infra id
    for member in plan.selected_team:
        assert member.model in VALID_MODELS, member.model
    # constitutional control is always present (rule 4: no secret access)
    assert "no_secret_access" in plan.risk_controls
    # roles mirror the team, and the team is non-empty
    assert plan.roles == [m.role for m in plan.selected_team]
    assert plan.selected_team
    assert plan.reasoning_summary


def test_team_members_are_diverse_when_possible(analyzer, graph):
    plan = _plan(analyzer, graph, "이 Python repo 버그 고치고 테스트 추가해줘")
    models = [m.model for m in plan.selected_team]
    assert len(models) == len(set(models))  # no duplicate seat


# --- CLI --------------------------------------------------------------------

def test_cli_plan_team(monkeypatch, capsys):
    monkeypatch.setenv("AMMO_ROOT", str(REPO_ROOT))
    code = cli.main(["plan-team", "이 Python repo 버그 고치고 테스트 추가해줘"])
    out = capsys.readouterr().out
    assert code == 0
    data = json.loads(out)
    assert data["selected_system"] == "coding"
    assert data["selected_team"][1] == {"role": "builder", "model": "codex_gpt5"}


# --- primary model anchors the lead seat (summon config wiring) ----------------

def test_qualified_primary_breaks_the_lead_seat_tie(graph, analyzer):
    # researcher seat is a genuine static tie (claude fable vs qwen):
    # the primary anchor decides it.
    task = analyzer.analyze("이 주제 자료 조사해줘")
    default = TeamFormer(graph).form(task)
    anchored = TeamFormer(graph, primary="qwen_planner_mock").form(task)
    assert default.selected_team[0].model == "claude_a_fable"  # tie -> lexical
    assert anchored.selected_team[0].model == "qwen_planner_mock" # tie -> primary
    assert any("primary model (summoning host)" in n for n in anchored.notes)


def test_primary_cannot_dethrone_a_clear_static_winner(graph, analyzer):
    # coding planner seat: claude fable leads qwen by 2 (> the 1.5 anchor bonus)
    task = analyzer.analyze("이 python repo 버그 고쳐줘")
    plan = TeamFormer(graph, primary="qwen_planner_mock").form(task)
    assert plan.selected_team[0].model == "claude_a_fable"


def test_unqualified_primary_has_no_effect(graph, analyzer):
    task = analyzer.analyze("이 주제 자료 조사해줘")
    plan = TeamFormer(graph, primary="kimi_coder_mock").form(task)  # no researcher fit
    assert plan.selected_team[0].model == "claude_a_fable"
    assert not any("primary model" in n for n in plan.notes)


def test_primary_only_affects_lead_not_other_seats(graph, analyzer):
    task = analyzer.analyze("이 python repo 버그 고쳐줘")
    plan = TeamFormer(graph, primary="kimi_coder_mock").form(task)   # builder-fit model
    # kimi qualifies for builder, not the lead planner seat -> nothing changes
    assert plan.selected_team[0].model == "claude_a_fable"
    assert plan.selected_team[1].model == "codex_gpt5"
