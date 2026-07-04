"""Tests for role assignment (ammo.roleplan) and its effect on team formation.

The user authors a four-slot role assignment (orchestrator/critic/worker/builder).
It is persisted in ammo.config.yaml and is *authority*: an assigned model wins the
seat that maps to its slot, even when another model scores higher by capability.
"""

from pathlib import Path

import pytest

from ammo import roleplan
from ammo.config import AmmoConfig, load_config, save_config
from ammo.kernel.capability_graph import CapabilityGraph
from ammo.kernel.task_understanding import TaskAnalyzer
from ammo.kernel.team_formation import TeamFormer

REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def graph():
    return CapabilityGraph.from_registry(root=REPO_ROOT)


@pytest.fixture(scope="module")
def analyzer():
    return TaskAnalyzer(systems=[])


# --- config round-trip ------------------------------------------------------

def test_config_roundtrips_roles(tmp_path):
    cfg = AmmoConfig(host="claude-code",
                     roles={"orchestrator": "claude_b_fable", "critic": "claude_a_opus"})
    save_config(tmp_path, cfg)
    loaded = load_config(tmp_path)
    assert loaded.roles == {"orchestrator": "claude_b_fable", "critic": "claude_a_opus"}


def test_config_drops_empty_role_values(tmp_path):
    save_config(tmp_path, AmmoConfig(roles={"worker": "", "builder": "codex_gpt5"}))
    assert load_config(tmp_path).roles == {"builder": "codex_gpt5"}


# --- plan_roles: the interview ---------------------------------------------

def test_plan_offers_all_usable_and_marks_qualified(graph):
    plans = {p.slot: p for p in roleplan.plan_roles(graph=graph)}
    assert set(plans) == {"orchestrator", "critic", "worker", "builder"}

    orch = plans["orchestrator"]
    by_id = {c["model"]: c for c in orch.candidates}
    # planning/analyst-capable models are qualified for the orchestrator seat;
    # claude_b runs Fable 5 and is fully capable, so both A and B qualify.
    assert orch.proposed in {"claude_a_opus", "claude_b_fable"}
    assert by_id["claude_a_opus"]["qualified"] is True
    assert by_id["claude_b_fable"]["qualified"] is True
    # a pure coder is still offered for the seat (assignable), just not qualified
    assert by_id["codex_gpt5"]["qualified"] is False

    assert plans["critic"].proposed == "claude_b_fable"
    assert plans["builder"].proposed == "codex_gpt5"


def test_plan_restricts_to_usable_models(graph):
    plans = {p.slot: p for p in roleplan.plan_roles(
        graph=graph, usable_models=["claude_a_opus", "codex_gpt5"])}
    offered = {c["model"] for c in plans["orchestrator"].candidates}
    assert offered == {"claude_a_opus", "codex_gpt5"}


# --- apply_roles: persistence + warnings -----------------------------------

def test_apply_persists_and_anchors_primary(tmp_path, graph):
    config, warnings = roleplan.apply_roles(
        tmp_path,
        {"orchestrator": "claude_b_fable", "critic": "claude_a_opus",
         "worker": "claude_a_haiku", "builder": "codex_gpt5"},
        graph=graph)
    assert config.roles["orchestrator"] == "claude_b_fable"
    # orchestrator's model becomes the lead-seat anchor
    assert config.primary_model == "claude_b_fable"
    # assigning a non-critic model to critic warns (but does not block)
    assert any("claude_a_opus" in w and "critic" in w for w in warnings)
    # and it round-trips to disk
    assert load_config(tmp_path).roles["critic"] == "claude_a_opus"


def test_apply_ignores_unknown_slots(tmp_path, graph):
    config, _ = roleplan.apply_roles(tmp_path, {"wizard": "claude_a_opus"}, graph=graph)
    assert config.roles == {}


# --- team formation honors the assignment (authority) ----------------------

def test_assignment_wins_seat_over_capability(analyzer, graph):
    """A/B swap without touching the registry: assign the critic-model as
    orchestrator and the planner-model as critic; both must win their seats."""
    task = analyzer.analyze("이 Python repo 버그 고치고 테스트 추가해줘")  # high-risk coding
    assignments = {
        "orchestrator": "claude_b_fable",   # not planning-qualified
        "critic": "claude_a_opus",        # not critic-qualified
        "builder": "claude_a_haiku",
    }
    plan = TeamFormer(graph, role_assignments=assignments).form(task)
    seats = {m.role: m.model for m in plan.selected_team}
    assert seats["planner"] == "claude_b_fable"      # orchestrator slot won the lead
    assert seats["critic"] == "claude_a_opus"      # critic slot won
    assert seats["builder"] == "claude_a_haiku"
    assert seats["test_runner"] == "local_test_runner"  # infra unaffected


def test_no_assignment_keeps_capability_defaults(analyzer, graph):
    task = analyzer.analyze("이 Python repo 버그 고치고 테스트 추가해줘")
    plan = TeamFormer(graph, role_assignments={}).form(task)
    seats = {m.role: m.model for m in plan.selected_team}
    assert seats["planner"] == "claude_a_opus"
    assert seats["critic"] == "claude_b_fable"


def test_unavailable_assigned_model_falls_back(analyzer, graph):
    """An assignment to a disabled/unknown model is silently ignored (the seat
    falls back to capability scoring) — never leaves the seat empty."""
    task = analyzer.analyze("이 Python repo 버그 고치고 테스트 추가해줘")
    plan = TeamFormer(graph, role_assignments={"critic": "ghost_model"}).form(task)
    seats = {m.role: m.model for m in plan.selected_team}
    assert seats["critic"] == "claude_b_fable"  # unchanged default


# --- informational internal mapping ----------------------------------------

def test_internal_mapping_shape():
    rows = roleplan.internal_mapping({"orchestrator": "claude_b_fable"})
    orch = next(r for r in rows if r["slot"] == "orchestrator")
    assert orch["model"] == "claude_b_fable"
    assert orch["internal_roles"] == ["router", "analyst", "synthesizer"]


# --- per-workspace team binding --------------------------------------------

def test_per_system_roles_roundtrip(tmp_path, graph):
    roles, warnings = roleplan.apply_roles_to_system(
        tmp_path, "coding", {"critic": "claude_a_haiku"}, graph=graph)
    assert roles == {"critic": "claude_a_haiku"}
    assert roleplan.system_roles(tmp_path, "coding") == {"critic": "claude_a_haiku"}
    assert roleplan.system_roles(tmp_path, "research") == {}   # untouched system


def test_per_workspace_overrides_global_for_that_system(tmp_path, graph, analyzer):
    from ammo.commands.common import _load_role_assignments

    save_config(tmp_path, AmmoConfig(roles={
        "orchestrator": "claude_b_fable", "critic": "claude_a_opus",
        "worker": "codex_gpt5", "builder": "codex_gpt5"}))
    roleplan.apply_roles_to_system(tmp_path, "coding", {"critic": "claude_a_haiku"}, graph=graph)

    coding = analyzer.analyze("이 python repo 버그 고쳐줘")        # candidate system: coding
    assert coding.candidate_systems[:1] == ["coding"]
    merged = _load_role_assignments(tmp_path, coding)
    assert merged["critic"] == "claude_a_haiku"                   # per-workspace override
    assert merged["orchestrator"] == "claude_b_fable"            # unset seats inherit global

    research = analyzer.analyze("이 논문들 조사해서 근거랑 같이 정리해줘")  # different system
    assert _load_role_assignments(tmp_path, research)["critic"] == "claude_a_opus"  # global


def test_per_workspace_team_wins_the_seat_in_formation(tmp_path, graph, analyzer):
    from ammo.commands.common import _load_role_assignments

    save_config(tmp_path, AmmoConfig(roles={"critic": "claude_b_fable"}))
    roleplan.apply_roles_to_system(tmp_path, "coding", {"critic": "claude_a_haiku"}, graph=graph)
    task = analyzer.analyze("이 Python repo 버그 고치고 테스트 추가해줘")   # high-risk coding
    assignments = _load_role_assignments(tmp_path, task)
    plan = TeamFormer(graph, role_assignments=assignments).form(task)
    seats = {m.role: m.model for m in plan.selected_team}
    assert seats["critic"] == "claude_a_haiku"                    # workspace team wins
