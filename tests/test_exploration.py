"""Tests for deterministic epsilon-greedy exploration (annealed)."""

from pathlib import Path

import pytest

from ammo.kernel.capability_graph import CapabilityGraph
from ammo.kernel.task_understanding import TaskAnalyzer
from ammo.kernel.team_formation import TeamFormer
from ammo.memory import MemoryAdvisor
from ammo.memory.advisor import EPSILON_BASE

REPO_ROOT = Path(__file__).resolve().parents[1]


def _advisor(attempts, tag="research", model="qwen_planner_mock"):
    stats = {(model, tag): {"attempts": attempts, "successes": attempts,
                            "average_confidence": 0.9,
                            "average_cost": 0.0, "average_tokens": 10}}
    return MemoryAdvisor(stats, {})


# --- the schedule itself ---------------------------------------------------------

def test_epsilon_anneals_with_experience():
    eps = [_advisor(n).exploration_state("research")[1] for n in (0, 10, 40, 100)]
    assert eps[0] == EPSILON_BASE
    assert eps == sorted(eps, reverse=True)          # monotonically decreasing
    assert eps[-1] < EPSILON_BASE / 2                # meaningfully annealed


def test_schedule_is_deterministic_and_fires_at_the_epsilon_rate():
    fires = [n for n in range(1, 61)
             if _advisor(n).exploration_state("research")[0]]
    assert fires, "exploration never fires"
    assert 4 <= len(fires) <= 14                     # ~ε share of 60 attempts
    # deterministic: same history -> same answer
    assert fires == [n for n in range(1, 61)
                     if _advisor(n).exploration_state("research")[0]]


def test_cold_start_does_not_explore():
    active, _, n = MemoryAdvisor({}, {}).exploration_state("research")
    assert n == 0 and active is False                # nothing known -> pure static


# --- dethroning a stuck winner ------------------------------------------------------

@pytest.fixture(scope="module")
def graph():
    return CapabilityGraph.from_registry(root=REPO_ROOT)


@pytest.fixture(scope="module")
def analyzer():
    return TaskAnalyzer(systems=[])


def test_exploration_run_dethrones_the_incumbent(graph, analyzer):
    task = analyzer.analyze("이 주제 자료 조사해줘")     # researcher seat: static tie
    # n=5 is a scheduled exploration attempt; qwen is the entrenched winner
    exploring = TeamFormer(graph, memory=_advisor(5)).form(task)
    assert exploring.selected_team[0].model != "qwen_planner_mock"
    assert any("exploration run" in n for n in exploring.notes)


def test_off_schedule_run_exploits_the_incumbent(graph, analyzer):
    task = analyzer.analyze("이 주제 자료 조사해줘")
    # n=7 is not a scheduled attempt -> the strong history wins as usual
    exploiting = TeamFormer(graph, memory=_advisor(7)).form(task)
    assert exploiting.selected_team[0].model == "qwen_planner_mock"
    assert not any("exploration run" in n for n in exploiting.notes)


def test_nudge_targets_only_the_least_tried(graph, analyzer):
    # both models have history; the veteran must not receive the nudge
    stats = {
        ("qwen_planner_mock", "research"): {"attempts": 4, "successes": 4,
                                            "average_confidence": 0.9},
        ("claude_a_planner", "research"): {"attempts": 1, "successes": 0,
                                           "average_confidence": 0.2},
    }
    advisor = MemoryAdvisor(stats, {})
    active, _, _ = advisor.exploration_state("research")
    assert active                                     # n=5 fires
    veteran, _ = advisor.bonus("qwen_planner_mock", "researcher", "research")
    rookie, why = advisor.bonus("claude_a_planner", "researcher", "research")
    assert rookie > veteran                           # least-tried outbids
    assert any("exploration run" in r for r in why)
