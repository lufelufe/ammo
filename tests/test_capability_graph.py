"""Tests for Capability Graph v0 (Milestone 5).

Loads the real registry fleet, checks node shape and queries, and verifies that
TaskVector→model scoring ranks the right kind of model first. No model is called.
"""

from pathlib import Path

import pytest

from ammo import cli
from ammo.kernel.capability_graph import (
    CapabilityGraph,
    ModelNode,
    score_models,
    task_needs,
)
from ammo.kernel.task_understanding import TaskAnalyzer

REPO_ROOT = Path(__file__).resolve().parents[1]

EXPECTED_MODELS = {
    "claude_a_planner",
    "codex_builder",
    "claude_b_critic",
    "qwen_planner_mock",
    "kimi_coder_mock",
    "gpt_oss_critic_mock",
    "fast_worker_mock",
    "claude_haiku_fast",
    "claude_sonnet_worker",
    "local_test_runner",
}


@pytest.fixture(scope="module")
def graph():
    return CapabilityGraph.from_registry(root=REPO_ROOT)


@pytest.fixture(scope="module")
def analyzer():
    return TaskAnalyzer(systems=[])


# --- ModelNode --------------------------------------------------------------

def test_model_node_from_dict_defaults():
    node = ModelNode.from_dict({"id": "x"})
    assert node.id == "x"
    assert node.roles == [] and node.capabilities == []
    assert node.cost_class == "standard" and node.warm_status == "cold"
    assert node.enabled is True


def test_model_node_from_dict_full():
    node = ModelNode.from_dict(
        {"id": "m", "provider": "oss", "roles": ["critic"], "capabilities": ["review"],
         "context_window": 32000, "cost_class": "cheap", "warm_status": "warm", "enabled": False}
    )
    assert node.provider == "oss"
    assert node.context_window == 32000
    assert node.enabled is False


# --- graph loading & queries ------------------------------------------------

def test_graph_loads_the_registry_models(graph):
    assert {n.id for n in graph.nodes} == EXPECTED_MODELS


def test_all_nodes_have_required_fields(graph):
    for node in graph.nodes:
        assert node.provider and node.adapter
        assert node.roles and node.capabilities
        assert node.context_window > 0
        assert node.cost_class and node.latency_class and node.warm_status


def test_by_role_and_capability(graph):
    coders = {n.id for n in graph.by_capability("coding")}
    assert coders == {"codex_builder", "kimi_coder_mock"}
    critics = {n.id for n in graph.by_role("critic")}
    assert critics == {"claude_b_critic", "gpt_oss_critic_mock"}


def test_get_returns_node_or_none(graph):
    assert graph.get("codex_builder").provider == "openai"
    assert graph.get("nope") is None


def test_disabled_nodes_excluded_from_enabled_and_scoring(analyzer):
    graph = CapabilityGraph(
        [
            ModelNode(id="off", roles=["implementer"], capabilities=["coding"], enabled=False),
            ModelNode(id="on", roles=["implementer"], capabilities=["coding"], enabled=True),
        ]
    )
    assert {n.id for n in graph.enabled()} == {"on"}
    ranked = score_models(analyzer.analyze("fix a bug"), graph)
    assert {s.model_id for s in ranked} == {"on"}


# --- scoring ----------------------------------------------------------------

def test_task_needs_for_coding(analyzer):
    task = analyzer.analyze("이 Python repo 버그 고치고 테스트 추가해줘")
    primary, secondary, caps = task_needs(task)
    assert "implementer" in primary
    assert {"reviewer", "critic"} <= secondary  # from needs_tests
    assert "coding" in caps


def test_coding_task_ranks_a_coder_first(graph, analyzer):
    task = analyzer.analyze("이 Python repo 버그 고치고 테스트 추가해줘")
    ranked = score_models(task, graph)
    assert ranked[0].model_id == "codex_builder"
    assert ranked[1].model_id == "kimi_coder_mock"


def test_verify_task_ranks_a_critic_first(graph, analyzer):
    task = analyzer.analyze("투자 리서치 보고서 검증해줘")
    ranked = score_models(task, graph)
    assert ranked[0].model_id in {"claude_b_critic", "gpt_oss_critic_mock"}
    top_two = {ranked[0].model_id, ranked[1].model_id}
    assert top_two == {"claude_b_critic", "gpt_oss_critic_mock"}
    # a pure coder must not win a verification task
    assert ranked[0].model_id not in {"codex_builder", "kimi_coder_mock"}


def test_scoring_is_deterministic_and_sorted(graph, analyzer):
    ranked = score_models(analyzer.analyze("write a blog post"), graph)
    scores = [s.score for s in ranked]
    assert scores == sorted(scores, reverse=True)
    # every enabled node is scored
    assert len(ranked) == len(graph.enabled())


def test_reasons_are_populated_for_top_pick(graph, analyzer):
    ranked = score_models(analyzer.analyze("fix a bug and add tests"), graph)
    assert ranked[0].reasons  # non-empty explanation


# --- CLI --------------------------------------------------------------------

def test_cli_list_models(monkeypatch, capsys):
    monkeypatch.setenv("AMMO_ROOT", str(REPO_ROOT))
    code = cli.main(["list-models"])
    out = capsys.readouterr().out
    assert code == 0
    for model_id in EXPECTED_MODELS:
        assert model_id in out


def test_cli_score_models(monkeypatch, capsys):
    monkeypatch.setenv("AMMO_ROOT", str(REPO_ROOT))
    code = cli.main(["score-models", "투자 리서치 보고서 검증해줘"])
    out = capsys.readouterr().out
    assert code == 0
    assert "Ranked models:" in out
    assert "claude_b_critic" in out
