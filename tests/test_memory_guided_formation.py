"""Tests for Memory-guided Team Formation (Milestone 11).

Memory advises, the kernel decides: recorded performance nudges model selection
within capability/risk/template guardrails. Uses the real capability graph and a
directly-constructed MemoryAdvisor for precise control.
"""

import os
from pathlib import Path

import pytest

from ammo import cli
from ammo.kernel.capability_graph import CapabilityGraph
from ammo.kernel.task_understanding import TaskAnalyzer
from ammo.kernel.team_formation import TeamFormer
from ammo.memory import MemoryAdvisor, MemoryStore

REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def graph():
    return CapabilityGraph.from_registry(root=REPO_ROOT)


@pytest.fixture(scope="module")
def analyzer():
    return TaskAnalyzer(systems=[])


def _advisor(model_stats=None, best_teams=None):
    return MemoryAdvisor(model_stats or {}, best_teams or {})


# --- advisor bonus rules ----------------------------------------------------

def test_cold_start_gives_no_bonus():
    bonus, reasons = _advisor().bonus("codex_builder", "builder", "coding")
    assert bonus == 0.0 and reasons == []


def test_below_min_attempts_gives_no_bonus():
    adv = _advisor({("m", "coding"): {"attempts": 1, "successes": 1, "average_confidence": 0.9}})
    assert adv.bonus("m", "builder", "coding")[0] == 0.0


def test_strong_history_positive_weak_history_negative():
    good = _advisor({("m", "coding"): {"attempts": 4, "successes": 4, "average_confidence": 0.8}})
    bad = _advisor({("m", "coding"): {"attempts": 4, "successes": 0, "average_confidence": 0.2}})
    assert good.bonus("m", "builder", "coding")[0] > 0
    assert bad.bonus("m", "builder", "coding")[0] < 0


def test_bonus_is_capped():
    adv = _advisor({("m", "coding"): {"attempts": 99, "successes": 99, "average_confidence": 1.0}},
                   {"coding": {"team_signature": "builder:m", "attempts": 9, "successes": 9,
                               "average_confidence": 1.0}})
    assert adv.bonus("m", "builder", "coding")[0] <= 2.0


def test_synergy_bonus_for_winning_team_member():
    adv = _advisor(best_teams={"coding": {"team_signature": "builder:m+critic:c",
                                          "attempts": 3, "successes": 3, "average_confidence": 0.8}})
    assert adv.bonus("m", "builder", "coding")[0] > 0        # m held builder in winner
    assert adv.bonus("m", "critic", "coding")[0] == 0.0      # not in the critic seat


# --- team formation flips within guardrails --------------------------------

def _coding_stats(good="kimi_coder_mock", bad="codex_builder"):
    return {
        (good, "coding"): {"attempts": 3, "successes": 3, "average_confidence": 0.85},
        (bad, "coding"): {"attempts": 3, "successes": 0, "average_confidence": 0.15},
    }


def test_memory_flips_builder_pick(graph, analyzer):
    task = analyzer.analyze("이 python repo 버그 고쳐줘")  # high-risk coding, static tie -> codex
    static = TeamFormer(graph).form(task)
    guided = TeamFormer(graph, memory=_advisor(_coding_stats())).form(task)

    builder_static = next(m.model for m in static.selected_team if m.role == "builder")
    builder_guided = next(m.model for m in guided.selected_team if m.role == "builder")
    assert builder_static == "codex_builder"
    assert builder_guided == "kimi_coder_mock"
    assert any("kimi_coder_mock over codex_builder" in n for n in guided.notes)


def test_memory_never_overrides_capability_guardrail(graph, analyzer):
    """A non-coder with amazing coding memory must NOT take the builder seat."""
    task = analyzer.analyze("이 python repo 버그 고쳐줘")
    # claude_a_planner has no coding capability / implementer role
    stats = {("claude_a_planner", "coding"): {"attempts": 9, "successes": 9, "average_confidence": 1.0}}
    guided = TeamFormer(graph, memory=_advisor(stats)).form(task)
    builder = next(m.model for m in guided.selected_team if m.role == "builder")
    assert builder in {"codex_builder", "kimi_coder_mock"}  # still a real coder


def test_formation_is_deterministic(graph, analyzer):
    task = analyzer.analyze("이 python repo 버그 고쳐줘")
    adv = _advisor(_coding_stats())
    a = TeamFormer(graph, memory=adv).form(task).to_dict()
    b = TeamFormer(graph, memory=adv).form(task).to_dict()
    assert a == b


def test_no_memory_matches_static(graph, analyzer):
    task = analyzer.analyze("이 python repo 버그 고쳐줘")
    static = TeamFormer(graph).form(task)
    guided_none = TeamFormer(graph, memory=None).form(task)
    assert [m.to_dict() for m in static.selected_team] == [m.to_dict() for m in guided_none.selected_team]
    assert guided_none.notes == []


# --- advisor from a real store ---------------------------------------------

def test_advisor_from_store(tmp_path):
    store = MemoryStore(tmp_path / "m.sqlite")
    for i in range(3):
        store.record_run(run_id=f"r{i}", timestamp=f"2026-01-0{i+1}", domain="coding", tags=[],
                         selected_system="coding", model_ids=["kimi_coder_mock"],
                         team_signature="builder:kimi_coder_mock", confidence_score=0.85)
    adv = MemoryAdvisor.from_store(store)
    store.close()
    assert adv.bonus("kimi_coder_mock", "builder", "coding")[0] > 0


# --- CLI --------------------------------------------------------------------

@pytest.fixture
def ammo_root(tmp_path, monkeypatch):
    root = tmp_path / "root"
    root.mkdir()
    for name in ("registry", "systems"):
        os.symlink(REPO_ROOT / name, root / name)
    for name in ("runtime", "memory", "vaults"):
        (root / name).mkdir()
    monkeypatch.setenv("AMMO_ROOT", str(root))
    return root


def test_cli_plan_team_no_memory_flag(ammo_root, capsys):
    # seed memory so kimi is the coding winner
    with MemoryStore.open(ammo_root) as store:
        for i in range(3):
            store.record_run(run_id=f"r{i}", timestamp=f"2026-01-0{i+1}", domain="coding", tags=[],
                             selected_system="coding", model_ids=["kimi_coder_mock"],
                             team_signature="builder:kimi_coder_mock", confidence_score=0.85)

    import json
    cli.main(["plan-team", "이 python repo 버그 고쳐줘"])
    guided = json.loads(capsys.readouterr().out)
    cli.main(["plan-team", "이 python repo 버그 고쳐줘", "--no-memory"])
    static = json.loads(capsys.readouterr().out)

    builder_guided = next(m["model"] for m in guided["selected_team"] if m["role"] == "builder")
    builder_static = next(m["model"] for m in static["selected_team"] if m["role"] == "builder")
    assert builder_guided == "kimi_coder_mock"
    assert builder_static == "codex_builder"
    assert static["notes"] == []
