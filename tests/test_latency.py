"""Tests for real latency: measured per call → stored → speed objective."""

from pathlib import Path

import pytest

from ammo.adapters import AdapterRequest, CommandAdapter
from ammo.economics import PricingBook
from ammo.memory import MemoryStore, MemoryAdvisor

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_command_adapter_stamps_wall_clock(monkeypatch):
    import time

    def slow_runner(cmd, stdin="", env=None):
        time.sleep(0.02)
        return 0, "answer"
    adapter = CommandAdapter("m", ["echo"], runner=slow_runner)
    resp = adapter.execute(AdapterRequest(role="r", model="m", task_input="x"))
    assert resp.usage.latency_ms is not None and resp.usage.latency_ms >= 15


def test_economics_aggregates_latency():
    from ammo.adapters import AdapterResponse, Usage

    book = PricingBook.load(REPO_ROOT)
    responses = [
        AdapterResponse(role="a", model="claude_a_opus", output="x",
                        usage=Usage(10, 5, latency_ms=1200.0)),
        AdapterResponse(role="b", model="claude_a_opus", output="y",
                        usage=Usage(10, 5, latency_ms=800.0)),
    ]
    econ = book.run_economics(responses)
    row = next(m for m in econ["by_model"] if m["model"] == "claude_a_opus")
    assert row["latency_ms"] == 1000.0                 # mean of the two calls


def test_store_records_and_averages_latency(tmp_path):
    with MemoryStore.open(tmp_path) as s:
        for lat in (1000.0, 2000.0):
            s.record_run(run_id=f"r{lat}", timestamp="t", domain="research", tags=[],
                         selected_system="research", model_ids=["claude_a_opus"],
                         team_signature="researcher:claude_a_opus", confidence_score=0.8,
                         model_usage={"claude_a_opus": {"tokens": 10, "cost": 0.01,
                                                           "latency_ms": lat}})
        perf = {(r["model_id"], r["task_tag"]): r for r in s.all_model_performance()}
        assert perf[("claude_a_opus", "research")]["average_latency"] == 1500.0


def test_speed_objective_uses_real_latency_when_present():
    # two models: A slow but light tokens, B fast but heavy tokens.
    # real latency must make B (fast) win under speed — opposite of the token proxy.
    stats = {
        ("A", "research"): {"attempts": 4, "successes": 2, "average_confidence": 0.5,
                            "average_tokens": 100, "average_cost": 0.0, "average_latency": 5000.0},
        ("B", "research"): {"attempts": 4, "successes": 2, "average_confidence": 0.5,
                            "average_tokens": 900, "average_cost": 0.0, "average_latency": 500.0},
    }
    advisor = MemoryAdvisor(stats, {})
    a_speed, a_why = advisor.bonus("A", "researcher", "research", objective="speed")
    b_speed, b_why = advisor.bonus("B", "researcher", "research", objective="speed")
    assert b_speed > a_speed                            # fast wall-clock wins
    assert any("fast" in w for w in b_why)              # labeled by latency, not tokens


def test_speed_falls_back_to_token_proxy_without_latency():
    stats = {
        ("A", "research"): {"attempts": 4, "successes": 2, "average_confidence": 0.5,
                            "average_tokens": 100, "average_cost": 0.0, "average_latency": 0.0},
        ("B", "research"): {"attempts": 4, "successes": 2, "average_confidence": 0.5,
                            "average_tokens": 900, "average_cost": 0.0, "average_latency": 0.0},
    }
    advisor = MemoryAdvisor(stats, {})
    a_speed, a_why = advisor.bonus("A", "researcher", "research", objective="speed")
    b_speed, _ = advisor.bonus("B", "researcher", "research", objective="speed")
    assert a_speed > b_speed                            # lighter tokens win (proxy)
    assert any("light" in w for w in a_why)
