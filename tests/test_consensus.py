"""Tests for measured consensus (P2): N-way lead sampling + checker comparison."""

from pathlib import Path

import pytest

from ammo.adapters import AdapterResponse, MockAdapter, Usage
from ammo.kernel.capability_graph import CapabilityGraph
from ammo.kernel.confidence import ConfidenceEngine
from ammo.kernel.executor import Runner
from ammo.kernel.executor.runner import CONSENSUS_INSTRUCTION
from ammo.kernel.task_understanding import TaskAnalyzer
from ammo.kernel.team_formation import TeamFormer

REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def graph():
    return CapabilityGraph.from_registry(root=REPO_ROOT)


@pytest.fixture(scope="module")
def analyzer():
    return TaskAnalyzer(systems=[])


def _consensus_plan(graph, analyzer):
    task = analyzer.analyze("이 주제 자료 조사하고 검증해줘")   # researcher+skeptic+synth
    former = TeamFormer(graph)
    plan = former.form(task)
    lead = plan.roles[0]
    alts = former.alternates(lead, task, exclude={plan.selected_team[0].model}, k=1)
    plan.consensus = {"role": lead, "models": alts}
    return task, plan


def test_alternates_are_qualified_and_distinct(graph, analyzer):
    task = analyzer.analyze("이 주제 자료 조사하고 검증해줘")
    former = TeamFormer(graph)
    plan = former.form(task)
    alts = former.alternates(plan.roles[0], task,
                             exclude={plan.selected_team[0].model}, k=2)
    assert alts and plan.selected_team[0].model not in alts
    assert len(set(alts)) == len(alts)


class AgreeingChecker(MockAdapter):
    def execute(self, request):
        if request.role == "skeptic":
            assert CONSENSUS_INSTRUCTION.splitlines()[0][:20] in request.context["instruction"]
            return AdapterResponse(role="skeptic", model=request.model,
                                   output="변형들을 비교했다.\nCONSENSUS: agree\nVERDICT: PASS",
                                   usage=Usage(1, 1))
        return super().execute(request)


class SplitChecker(MockAdapter):
    def execute(self, request):
        if request.role == "skeptic":
            return AdapterResponse(role="skeptic", model=request.model,
                                   output="CONSENSUS: split — 결론이 상반됨\nVERDICT: FAIL — 재검증 필요",
                                   usage=Usage(1, 1))
        return super().execute(request)


def test_variants_run_and_agreement_is_measured(graph, analyzer):
    task, plan = _consensus_plan(graph, analyzer)
    result = Runner(AgreeingChecker, mode="real").run(plan, task)

    lead = plan.consensus["role"]
    lead_rows = [r for r in result.responses if r.role == lead]
    assert len(lead_rows) == 1 + len(plan.consensus["models"])   # lead + alternates

    skeptic = next(r for r in result.responses if r.role == "skeptic")
    consensus = [e for e in skeptic.evidence if e.kind == "consensus"]
    assert consensus and consensus[0].ok is True

    report = ConfidenceEngine().assess(task, plan, result.responses, mode="real")
    assert any("measured consensus" in r for r in report.reasons_positive)
    assert not any("producer and checker agreed" in r for r in report.reasons_positive)


def test_split_consensus_lowers_confidence(graph, analyzer):
    task, plan = _consensus_plan(graph, analyzer)
    agree = Runner(AgreeingChecker, mode="real").run(plan, task)
    split = Runner(SplitChecker, mode="real").run(plan, task)
    engine = ConfidenceEngine()
    agree_score = engine.assess(task, plan, agree.responses, mode="real").confidence_score
    split_report = engine.assess(task, plan, split.responses, mode="real")
    assert split_report.confidence_score < agree_score
    assert any("결론이 상반됨" in r for r in split_report.reasons_negative)


def test_without_consensus_the_proxy_remains(graph, analyzer):
    task = analyzer.analyze("이 주제 자료 조사하고 검증해줘")
    plan = TeamFormer(graph).form(task)
    result = Runner(MockAdapter).run(plan, task)
    report = ConfidenceEngine().assess(task, plan, result.responses)
    joined = " ".join(report.reasons_positive)
    assert "measured consensus" not in joined                    # proxy path only


def test_cli_consensus_flag(tmp_path, monkeypatch, capsys):
    import os, shutil
    from ammo import cli

    root = tmp_path / "root"
    root.mkdir()
    os.symlink(REPO_ROOT / "registry", root / "registry")
    shutil.copytree(REPO_ROOT / "systems", root / "systems")
    for name in ("runtime", "memory", "vaults"):
        (root / name).mkdir()
    monkeypatch.setenv("AMMO_ROOT", str(root))

    code = cli.main(["run", "--mock", "--consensus", "2",
                     "이 주제 자료 조사하고 검증해줘"])
    out = capsys.readouterr().out
    assert code == 0
    assert "consensus:" in out and "sampled by 2 models" in out
