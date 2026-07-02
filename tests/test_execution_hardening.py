"""Tests for execution hardening: checker verdict protocol + step retries +
real-mode evidence honesty."""

from pathlib import Path

import pytest

from ammo.adapters import AdapterResponse, Evidence, MockAdapter, Usage
from ammo.kernel.capability_graph import CapabilityGraph
from ammo.kernel.confidence import ConfidenceEngine
from ammo.kernel.executor import Runner
from ammo.kernel.executor.runner import VERDICT_INSTRUCTION, _parse_verdict
from ammo.kernel.task_understanding import TaskAnalyzer

REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def graph():
    return CapabilityGraph.from_registry(root=REPO_ROOT)


@pytest.fixture(scope="module")
def analyzer():
    return TaskAnalyzer(systems=[])


def _plan(graph, analyzer, text="이 주제 자료 조사하고 검증해줘"):
    task = analyzer.analyze(text)
    from ammo.kernel.team_formation import TeamFormer

    return task, TeamFormer(graph).form(task)


# --- verdict parsing -------------------------------------------------------------

def test_parse_verdict_variants():
    assert _parse_verdict("...분석...\nVERDICT: PASS") == (True, "")
    ok, reason = _parse_verdict("리뷰 결과\nVERDICT: FAIL — 출처가 정의와 모순")
    assert ok is False and "모순" in reason
    assert _parse_verdict("verdict: pass") == (True, "")     # case-insensitive
    assert _parse_verdict("판정 없음") is None
    # the FINAL verdict line wins (model may quote the instruction earlier)
    ok, _ = _parse_verdict("'VERDICT: FAIL' 형식으로 끝내라고 했다.\n분석 결과 문제 없음.\nVERDICT: PASS")
    assert ok is True


# --- runner: instruction injection + verdict evidence ------------------------------

class ScriptedAdapter(MockAdapter):
    """Returns scripted outputs per role; records requests."""

    outputs = {}
    seen = []

    def execute(self, request):
        ScriptedAdapter.seen.append(request)
        out = ScriptedAdapter.outputs.get(request.role)
        if out is None:
            return super().execute(request)
        return AdapterResponse(role=request.role, model=request.model, output=out,
                               usage=Usage(1, 1))


def test_checker_gets_verdict_instruction_and_evidence(graph, analyzer):
    ScriptedAdapter.outputs = {"skeptic": "검토 완료.\nVERDICT: FAIL — 근거 부족"}
    ScriptedAdapter.seen = []
    task, plan = _plan(graph, analyzer)
    assert "skeptic" in plan.roles
    result = Runner(ScriptedAdapter, mode="real").run(plan, task)

    skeptic_req = next(r for r in ScriptedAdapter.seen if r.role == "skeptic")
    assert skeptic_req.context["instruction"] == VERDICT_INSTRUCTION
    researcher_req = next(r for r in ScriptedAdapter.seen if r.role == "researcher")
    assert "instruction" not in researcher_req.context      # checkers only

    skeptic = next(r for r in result.responses if r.role == "skeptic")
    review = [ev for ev in skeptic.evidence if ev.kind == "review"]
    assert len(review) == 1 and review[0].ok is False
    assert "근거 부족" in review[0].summary


def test_verdict_fail_lowers_real_confidence(graph, analyzer):
    task, plan = _plan(graph, analyzer)
    engine = ConfidenceEngine()

    ScriptedAdapter.outputs = {"skeptic": "좋음.\nVERDICT: PASS"}
    passed = Runner(ScriptedAdapter, mode="real").run(plan, task)
    ScriptedAdapter.outputs = {"skeptic": "문제 있음.\nVERDICT: FAIL — 데이터 오류"}
    failed = Runner(ScriptedAdapter, mode="real").run(plan, task)

    pass_report = engine.assess(task, plan, passed.responses, mode="real")
    fail_report = engine.assess(task, plan, failed.responses, mode="real")
    assert fail_report.confidence_score < pass_report.confidence_score
    assert any("데이터 오류" in r for r in fail_report.reasons_negative)


def test_mock_checker_review_evidence_not_duplicated(graph, analyzer):
    # MockAdapter's critic already emits review evidence — no verdict double-count
    task, plan = _plan(graph, analyzer, "이 python repo 버그 고쳐줘")
    result = Runner(MockAdapter).run(plan, task)
    critic = next(r for r in result.responses if r.role == "critic")
    assert len([ev for ev in critic.evidence if ev.kind == "review"]) == 1


# --- retries ------------------------------------------------------------------------

class FlakyAdapter(MockAdapter):
    calls = 0

    def execute(self, request):
        FlakyAdapter.calls += 1
        if FlakyAdapter.calls == 1:
            return AdapterResponse(role=request.role, model=request.model, output="")
        return AdapterResponse(role=request.role, model=request.model,
                               output="recovered answer", usage=Usage(1, 1))


class DeadAdapter(MockAdapter):
    calls = 0

    def execute(self, request):
        DeadAdapter.calls += 1
        return AdapterResponse(role=request.role, model=request.model,
                               output="(command exited 1)")


def test_empty_output_is_retried_once(graph, analyzer):
    FlakyAdapter.calls = 0
    task, plan = _plan(graph, analyzer, "일정 정리해줘")   # 1-member team
    result = Runner(FlakyAdapter, mode="real").run(plan, task)
    assert FlakyAdapter.calls == 2
    resp = result.responses[0]
    assert resp.output == "recovered answer"
    inv = [ev for ev in resp.evidence if ev.kind == "invocation"]
    assert len(inv) == 1 and inv[0].ok is True             # retry succeeded


def test_retry_is_capped(graph, analyzer):
    DeadAdapter.calls = 0
    task, plan = _plan(graph, analyzer, "일정 정리해줘")
    result = Runner(DeadAdapter, mode="real").run(plan, task)
    assert DeadAdapter.calls == 2                          # 1 original + 1 retry only
    inv = [ev for ev in result.responses[0].evidence if ev.kind == "invocation"]
    assert inv and inv[0].ok is False


# --- real-mode evidence honesty ------------------------------------------------------

def test_majority_without_evidence_is_penalized_in_real_mode():
    from ammo.kernel.task_understanding import TaskVector
    from ammo.kernel.team_formation.execution_plan import ExecutionPlan, TeamMember

    engine = ConfidenceEngine()
    task = TaskVector(raw_input="x", domain="research", intent="answer", risk="low")
    team = [TeamMember("researcher", "a"), TeamMember("writer", "b"),
            TeamMember("synthesizer", "c")]
    plan = ExecutionPlan(selected_system="s", selected_team=team,
                         roles=[m.role for m in team], risk_controls=[])
    # 2 of 3 members evidence-free (some evidence exists, so this is the
    # majority-penalty path, not the blanket no-evidence penalty)
    bare = [AdapterResponse(role="researcher", model="a", output="x"),
            AdapterResponse(role="writer", model="b", output="y"),
            AdapterResponse(role="synthesizer", model="c", output="z",
                            evidence=[Evidence("result", "done", ok=True)])]
    backed = [AdapterResponse(role="researcher", model="a", output="x",
                              evidence=[Evidence("citation", "src", ok=True)]),
              AdapterResponse(role="writer", model="b", output="y",
                              evidence=[Evidence("draft", "done", ok=True)]),
              AdapterResponse(role="synthesizer", model="c", output="z",
                              evidence=[Evidence("result", "done", ok=True)])]
    bare_r = engine.assess(task, plan, bare, mode="real")
    backed_r = engine.assess(task, plan, backed, mode="real")
    assert bare_r.confidence_score < backed_r.confidence_score
    assert any("no structured evidence" in r for r in bare_r.reasons_negative)


# --- self-heal: gate miss + declared escalation -> one reinforced re-run ---------

import os
import shutil


@pytest.fixture
def heal_root(tmp_path, monkeypatch):
    root = tmp_path / "root"
    root.mkdir()
    os.symlink(REPO_ROOT / "registry", root / "registry")
    shutil.copytree(REPO_ROOT / "systems", root / "systems")
    for name in ("runtime", "memory", "vaults"):
        (root / name).mkdir()
    monkeypatch.setenv("AMMO_ROOT", str(root))
    return root


def test_self_heal_escalates_once_on_gate_miss(heal_root, capsys):
    from ammo import cli

    (heal_root / "systems" / "personal" / ".ammo" / "limits.yaml").write_text(
        "apiVersion: ammo/v1\nkind: Limits\nsystem: personal\n"
        "confidence_gate: 0.95\nescalation: add_role:critic\n",
        encoding="utf-8",
    )
    code = cli.main(["run", "--mock", "오늘 할 일 정리해줘"])
    out = capsys.readouterr().out
    assert code == 0
    assert "self-heal: escalated (+critic)" in out          # reinforced re-run happened
    # personal 'briefing' workflow routes the team; the critic joins on top
    assert "team: analyst, synthesizer, critic" in out
    assert out.count("self-heal: escalated") == 1           # never loops


def test_no_self_heal_when_gate_passes(heal_root, capsys):
    from ammo import cli

    (heal_root / "systems" / "personal" / ".ammo" / "limits.yaml").write_text(
        "apiVersion: ammo/v1\nkind: Limits\nsystem: personal\n"
        "confidence_gate: 0.1\nescalation: add_role:critic\n",
        encoding="utf-8",
    )
    cli.main(["run", "--mock", "오늘 할 일 정리해줘"])
    out = capsys.readouterr().out
    assert "self-heal" not in out


def test_former_extra_roles_appends_known_position(heal_root):
    from ammo.kernel.capability_graph import CapabilityGraph
    from ammo.kernel.task_understanding import TaskAnalyzer
    from ammo.kernel.team_formation import TeamFormer

    graph = CapabilityGraph.from_registry(root=REPO_ROOT)
    task = TaskAnalyzer(systems=[]).analyze("오늘 할 일 정리해줘")
    plan = TeamFormer(graph).form(task, extra_roles=["critic", "nonsense_role"])
    assert plan.roles == ["fast_worker", "critic"]          # unknown role ignored
