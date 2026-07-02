"""Tests for the debate execution mode (P1): challenge -> rebuttal -> verdict."""

from pathlib import Path

import pytest

from ammo.adapters import AdapterResponse, MockAdapter, Usage
from ammo.kernel.capability_graph import CapabilityGraph
from ammo.kernel.confidence import ConfidenceEngine
from ammo.kernel.executor import Runner
from ammo.kernel.executor.runner import FINAL_VERDICT_INSTRUCTION, REBUTTAL_INSTRUCTION
from ammo.kernel.task_understanding import TaskAnalyzer
from ammo.kernel.team_formation import TeamFormer

REPO_ROOT = Path(__file__).resolve().parents[1]

DEBATE_WF = [{"id": "investment-intel",
              "stages": [{"role": "analyst"},
                         {"role": "critic", "debate": True},
                         {"role": "synthesizer"}],
              "confidence_gate": 0.7}]


@pytest.fixture(scope="module")
def graph():
    return CapabilityGraph.from_registry(root=REPO_ROOT)


@pytest.fixture(scope="module")
def analyzer():
    return TaskAnalyzer(systems=[])


def _plan(graph, analyzer):
    task = analyzer.analyze("포트폴리오 리밸런싱 전략 검토해줘")
    return task, TeamFormer(graph, workflows=DEBATE_WF).form(task)


def test_debate_spec_lands_on_the_plan(graph, analyzer):
    _, plan = _plan(graph, analyzer)
    assert plan.debate == {"proposer": "analyst", "challenger": "critic", "rounds": 1}


class DebateAdapter(MockAdapter):
    """analyst answers; critic objects first, passes after the rebuttal."""

    seen = []
    critic_calls = 0

    def execute(self, request):
        DebateAdapter.seen.append(request)
        if request.role == "critic":
            DebateAdapter.critic_calls += 1
            if DebateAdapter.critic_calls == 1:
                out = "근거가 약합니다.\nVERDICT: FAIL — 출처 없음"
            else:
                out = "재반론이 타당합니다.\nVERDICT: PASS"
            return AdapterResponse(role="critic", model=request.model,
                                   output=out, usage=Usage(1, 1))
        return super().execute(request)


def test_full_exchange_and_evidence_semantics(graph, analyzer):
    DebateAdapter.seen, DebateAdapter.critic_calls = [], 0
    task, plan = _plan(graph, analyzer)
    result = Runner(DebateAdapter, mode="real").run(plan, task)

    roles = [r.role for r in result.responses]
    assert roles == ["analyst", "critic", "analyst", "critic", "synthesizer"]

    rebuttal_req = DebateAdapter.seen[2]
    assert rebuttal_req.context["instruction"] == REBUTTAL_INSTRUCTION
    assert "출처 없음" in rebuttal_req.context["challenge"]     # objection handed over
    final_req = DebateAdapter.seen[3]
    assert final_req.context["instruction"] == FINAL_VERDICT_INSTRUCTION

    first_critic, final_critic = result.responses[1], result.responses[3]
    assert [e.kind for e in first_critic.evidence] == ["challenge"]   # downgraded
    review = [e for e in final_critic.evidence if e.kind == "review"]
    assert review and review[0].ok is True

    report = ConfidenceEngine().assess(task, plan, result.responses, mode="real")
    assert not any("unresolved objection" in r for r in report.reasons_negative)
    assert any("resolved through debate" in r for r in report.reasons_positive)
    assert any("required workflow completed" in r for r in report.reasons_positive)


class StubbornAdapter(DebateAdapter):
    def execute(self, request):
        if request.role == "critic":
            StubbornAdapter.critic_calls += 1
            return AdapterResponse(role="critic", model=request.model,
                                   output="여전히 부족합니다.\nVERDICT: FAIL — 미해결",
                                   usage=Usage(1, 1))
        return MockAdapter.execute(self, request)


def test_unresolved_debate_scores_as_objection(graph, analyzer):
    StubbornAdapter.critic_calls = 0
    task, plan = _plan(graph, analyzer)
    result = Runner(StubbornAdapter, mode="real").run(plan, task)
    report = ConfidenceEngine().assess(task, plan, result.responses, mode="real")
    assert any("미해결" in r for r in report.reasons_negative)   # final FAIL scores
    assert not any("resolved through debate" in r for r in report.reasons_positive)


def test_no_debate_flag_means_single_pass(graph, analyzer):
    plain = [{"id": "investment-intel",
              "stages": [{"role": "analyst"}, {"role": "critic"},
                         {"role": "synthesizer"}]}]
    task = analyzer.analyze("포트폴리오 리밸런싱 전략 검토해줘")
    plan = TeamFormer(graph, workflows=plain).form(task)
    assert plan.debate is None
    result = Runner(MockAdapter).run(plan, task)
    assert [r.role for r in result.responses] == ["analyst", "critic", "synthesizer"]
