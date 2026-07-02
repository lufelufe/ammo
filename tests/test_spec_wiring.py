"""Tests for spec wiring (M19): the per-system optimization specs actually
drive the engines — preferences→formation, limits→formation/gate,
verification→confidence, context.md + role memory→worker injection."""

import os
import shutil
from pathlib import Path

import pytest

from ammo import cli
from ammo.adapters import AdapterResponse, Evidence, MockAdapter
from ammo.kernel.capability_graph import CapabilityGraph
from ammo.kernel.confidence import ConfidenceEngine
from ammo.kernel.executor import Runner
from ammo.kernel.task_understanding import TaskAnalyzer, TaskVector
from ammo.kernel.team_formation import TeamFormer
from ammo.kernel.team_formation.execution_plan import ExecutionPlan, TeamMember

REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def graph():
    return CapabilityGraph.from_registry(root=REPO_ROOT)


@pytest.fixture(scope="module")
def analyzer():
    return TaskAnalyzer(systems=[])


# --- preferences.yaml -> formation ---------------------------------------------

def test_default_template_override(graph, analyzer):
    task = analyzer.analyze("이 python repo 버그 고쳐줘")            # normally coding_*
    plan = TeamFormer(graph, preferences={"default_template": "simple_fast"}).form(task)
    assert plan.roles == ["fast_worker"]
    assert "simple_fast" in plan.reasoning_summary


def test_model_bias_breaks_a_tie_for_qualified_model(graph, analyzer):
    task = analyzer.analyze("이 주제 자료 조사해줘")                 # researcher tie 7:7
    plain = TeamFormer(graph).form(task)
    biased = TeamFormer(graph, preferences={"model_bias": {"qwen_planner_mock": 1.0}}).form(task)
    assert plain.selected_team[0].model == "claude_a_planner"
    assert biased.selected_team[0].model == "qwen_planner_mock"
    assert any("system preference" in n for n in biased.notes)


def test_model_bias_is_clamped_below_capability_match(graph, analyzer):
    # even an absurd bias can't push an unqualified model past a capability fit
    task = analyzer.analyze("이 python repo 버그 고쳐줘")
    plan = TeamFormer(graph, preferences={"model_bias": {"fast_worker_mock": 99}}).form(task)
    assert plan.selected_team[0].model == "claude_a_planner"


# --- limits.yaml -> formation ---------------------------------------------------

def test_max_team_size_truncates_in_template_order(graph, analyzer):
    task = analyzer.analyze("이 python repo 버그 고쳐줘")
    full = TeamFormer(graph).form(task)
    capped = TeamFormer(graph, limits={"max_team_size": 2}).form(task)
    assert len(full.selected_team) > 2
    assert [m.role for m in capped.selected_team] == [m.role for m in full.selected_team][:2]


def test_cost_class_max_excludes_premium_members(graph, analyzer):
    task = analyzer.analyze("이 주제 자료 조사해줘")
    capped = TeamFormer(graph, limits={"cost_class_max": "standard"}).form(task)
    premium = {n.id for n in graph.nodes if n.cost_class == "premium"}
    assert not premium & {m.model for m in capped.selected_team}


def test_cost_cap_falls_back_when_unfillable(graph, analyzer):
    # a cap below every candidate must not leave seats empty
    task = analyzer.analyze("이 python repo 버그 고쳐줘")
    plan = TeamFormer(graph, limits={"cost_class_max": "cheap"}).form(task)
    assert all(m.model != "unassigned" for m in plan.selected_team)


# --- verification.yaml -> confidence ---------------------------------------------

def _mk(role, evidence):
    return AdapterResponse(role=role, model=f"m_{role}", output="out", evidence=evidence)


def test_declared_success_evidence_moves_the_score():
    engine = ConfidenceEngine()
    task = TaskVector(raw_input="x", domain="research", intent="answer", risk="low")
    plan = ExecutionPlan(selected_system="s", selected_team=[TeamMember("researcher", "m")],
                         roles=["researcher"], risk_controls=[])
    with_citation = [_mk("researcher", [Evidence("citation", "sourced", ok=True)])]
    without = [_mk("researcher", [Evidence("note", "unsourced", ok=True)])]
    spec = {"success_evidence": ["citation"]}
    hit = engine.assess(task, plan, with_citation, mode="real", verification=spec)
    miss = engine.assess(task, plan, without, mode="real", verification=spec)
    assert hit.confidence_score > miss.confidence_score
    assert any("citation" in r for r in hit.reasons_positive)
    assert any("missing: citation" in r for r in miss.reasons_negative)


# --- context.md + role memory -> worker injection ---------------------------------

class CapturingAdapter(MockAdapter):
    seen = []

    def execute(self, request):
        CapturingAdapter.seen.append(request)
        return super().execute(request)


def test_runner_injects_system_context_and_role_memory(graph, analyzer):
    CapturingAdapter.seen = []
    task = analyzer.analyze("이 주제 자료 조사해줘")
    plan = TeamFormer(graph).form(task)
    Runner(CapturingAdapter).run(
        plan, task,
        system_context="Research conventions: cite everything.",
        role_context={"researcher": "insight: past runs preferred primary sources"},
    )
    lead = CapturingAdapter.seen[0]
    assert lead.context["system_context"].startswith("Research conventions")
    assert "primary sources" in lead.context["role_memory"]
    others = CapturingAdapter.seen[1:]
    assert all("role_memory" not in r.context for r in others)   # per-role only
    assert all("system_context" in r.context for r in others)    # shared guidance


# --- end-to-end: specs in a pack drive a CLI run -----------------------------------

@pytest.fixture
def ammo_root(tmp_path, monkeypatch):
    root = tmp_path / "root"
    root.mkdir()
    os.symlink(REPO_ROOT / "registry", root / "registry")
    shutil.copytree(REPO_ROOT / "systems", root / "systems")
    for name in ("runtime", "memory", "vaults"):
        (root / name).mkdir()
    monkeypatch.setenv("AMMO_ROOT", str(root))
    return root


def test_cli_run_honors_pack_specs(ammo_root, capsys):
    ammo_dir = ammo_root / "systems" / "coding" / ".ammo"
    (ammo_dir / "limits.yaml").write_text(
        "apiVersion: ammo/v1\nkind: Limits\nsystem: coding\n"
        "max_team_size: 2\nconfidence_gate: 0.95\nescalation: add_role:critic\n",
        encoding="utf-8",
    )
    (ammo_dir / "verification.yaml").write_text(
        "apiVersion: ammo/v1\nkind: Verification\nsystem: coding\n"
        "success_evidence: [test_result]\n",
        encoding="utf-8",
    )
    code = cli.main(["run", "--mock", "이 python repo 버그 고쳐줘"])
    out = capsys.readouterr().out
    assert code == 0
    assert "team: planner, builder" in out                      # max_team_size: 2
    assert "gate: below the system confidence_gate (0.95)" in out
    assert "escalation: add_role:critic" in out


def test_required_outputs_gap_lowers_confidence():
    engine = ConfidenceEngine()
    task = TaskVector(raw_input="x", domain="research", intent="answer", risk="low")
    plan = ExecutionPlan(selected_system="s", selected_team=[TeamMember("researcher", "m")],
                         roles=["researcher"], risk_controls=[],
                         expected_outputs=["summary"])
    resp = [_mk("researcher", [Evidence("note", "done", ok=True)])]
    spec = {"required_outputs": ["summary", "citations"]}
    report = engine.assess(task, plan, resp, mode="real", verification=spec)
    assert any("not planned: citations" in r for r in report.reasons_negative)
    assert not any("not planned: summary" in r for r in report.reasons_negative)


def test_preferred_roles_lead_and_survive_the_cap(graph, analyzer):
    task = analyzer.analyze("이 python repo 버그 고쳐줘")   # planner,builder,critic,...
    plan = TeamFormer(graph,
                      preferences={"preferred_roles": ["critic"]},
                      limits={"max_team_size": 2}).form(task)
    assert plan.roles[0] == "critic"                        # moved to the lead seat
    assert "critic" in plan.roles and len(plan.roles) == 2  # survived the cap
