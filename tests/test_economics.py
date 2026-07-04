"""Tests for the efficiency protocol (M17): usage, pricing, cost, objectives."""

import json
import os
import shutil
from pathlib import Path

import pytest

from ammo import cli
from ammo.adapters import AdapterRequest, AdapterResponse, MockAdapter, Usage
from ammo.economics import ModelPrice, PricingBook
from ammo.kernel.capability_graph import CapabilityGraph
from ammo.kernel.task_understanding import TaskAnalyzer
from ammo.kernel.team_formation import TeamFormer
from ammo.memory import MemoryAdvisor, MemoryStore

REPO_ROOT = Path(__file__).resolve().parents[1]


# --- usage tracking ----------------------------------------------------------

def test_mock_adapter_reports_deterministic_usage():
    req = AdapterRequest(role="planner", model="m", task_input="fix the bug")
    a = MockAdapter("m").execute(req)
    b = MockAdapter("m").execute(req)
    assert a.usage is not None and a.usage.input_tokens > 0 and a.usage.output_tokens > 0
    assert a.usage.estimated is True
    assert a.usage.to_dict() == b.usage.to_dict()  # deterministic


def test_response_to_dict_includes_usage():
    resp = AdapterResponse(role="r", model="m", output="o",
                           usage=Usage(input_tokens=10, output_tokens=5))
    assert resp.to_dict()["usage"] == {"input_tokens": 10, "output_tokens": 5,
                                       "estimated": True, "latency_ms": None,
                                       "cost_usd": None}


# --- pricing book -------------------------------------------------------------

def test_pricing_book_loads_and_costs():
    book = PricingBook.load(REPO_ROOT)
    price = book.get("claude_a_opus")
    assert price is not None and price.billing == "subscription"
    # 1M in + 1M out at $5/$25 => $30
    assert price.cost(1_000_000, 1_000_000) == pytest.approx(30.0)
    assert book.get("kimi_coder_mock").cost(1_000_000, 1_000_000) == 0.0  # local


def test_run_economics_aggregates_and_flags_unpriced():
    book = PricingBook({"m1": ModelPrice("m1", "api", 10.0, 20.0)})
    responses = [
        AdapterResponse(role="a", model="m1", output="", usage=Usage(1000, 500)),
        AdapterResponse(role="b", model="ghost", output="", usage=Usage(100, 100)),
    ]
    econ = book.run_economics(responses)
    assert econ["model_count"] == 2
    assert econ["total_tokens"] == 1700
    assert econ["estimated_cost"] == pytest.approx((1000 * 10 + 500 * 20) / 1_000_000)
    assert econ["unpriced_models"] == ["ghost"]


def test_pricing_set_and_save_roundtrip(tmp_path):
    root = tmp_path / "root"
    (root / "registry").mkdir(parents=True)
    shutil.copy(REPO_ROOT / "registry" / "pricing.yaml", root / "registry" / "pricing.yaml")
    book = PricingBook.load(root)
    book.set_price("new_model", 1.5, 6.0, billing="api")
    book.save()
    reloaded = PricingBook.load(root)
    assert reloaded.get("new_model").price_per_mtok_out == 6.0
    assert reloaded.get("new_model").source == "manual"


def test_price_source_refresh_hook():
    class FakeSource:  # the user's future search module implements this shape
        def lookup(self, model_id):
            return ModelPrice(model_id, "api", 9.0, 27.0, source="search") if model_id == "x" else None

    book = PricingBook({})
    updated = book.refresh(FakeSource(), ["x", "unknown"])
    assert updated == ["x"] and book.get("x").source == "search"


# --- memory: cost in the improvement loop ------------------------------------

def test_record_run_stores_cost_aggregates(tmp_path):
    with MemoryStore(tmp_path / "m.sqlite") as mem:
        mem.record_run(run_id="r1", timestamp="t", domain="coding", tags=[],
                       selected_system="coding", model_ids=["a", "b"],
                       team_signature="s", confidence_score=0.8,
                       total_tokens=1000, estimated_cost=0.02,
                       model_usage={"a": {"tokens": 700, "cost": 0.015},
                                    "b": {"tokens": 300, "cost": 0.005}})
        perf = {m["model_id"]: m for m in mem.all_model_performance()}
        assert perf["a"]["average_tokens"] == 700 and perf["a"]["average_cost"] == 0.015
        team = mem.all_team_synergy()[0]
        assert team["average_cost"] == 0.02
        run = mem.list_runs()[0]
        assert run["total_tokens"] == 1000 and run["estimated_cost"] == 0.02


def test_old_db_migrates_cost_columns(tmp_path):
    import sqlite3

    db = tmp_path / "old.sqlite"
    conn = sqlite3.connect(str(db))
    conn.executescript(
        "CREATE TABLE runs (run_id TEXT PRIMARY KEY, timestamp TEXT, domain TEXT, tags TEXT,"
        " selected_system TEXT, selected_models TEXT, confidence_score REAL,"
        " outcome_status TEXT, user_feedback TEXT);"
        "CREATE TABLE model_performance (model_id TEXT, task_tag TEXT, attempts INTEGER,"
        " successes INTEGER, average_confidence REAL, last_used_at TEXT,"
        " PRIMARY KEY (model_id, task_tag));"
        "CREATE TABLE team_synergy (team_signature TEXT, task_tag TEXT, attempts INTEGER,"
        " successes INTEGER, average_confidence REAL, PRIMARY KEY (team_signature, task_tag));"
    )
    conn.commit()
    conn.close()
    with MemoryStore(db) as mem:  # must migrate all three tables
        mem.record_run(run_id="r", timestamp="t", domain="x", tags=[], selected_system="x",
                       model_ids=["m"], team_signature="s", confidence_score=0.7,
                       total_tokens=10, estimated_cost=0.001,
                       model_usage={"m": {"tokens": 10, "cost": 0.001}})
        assert mem.all_model_performance()[0]["average_cost"] == 0.001


# --- objectives: same task, different optimum --------------------------------

@pytest.fixture(scope="module")
def graph():
    return CapabilityGraph.from_registry(root=REPO_ROOT)


@pytest.fixture(scope="module")
def analyzer():
    return TaskAnalyzer(systems=[])


def test_cost_objective_prefers_local_models(graph, analyzer):
    task = analyzer.analyze("이 python repo 버그 고쳐줘")
    balanced = TeamFormer(graph).form(task)
    cheap = TeamFormer(graph, objective="cost").form(task)
    balanced_models = {m.model for m in balanced.selected_team}
    cheap_models = {m.model for m in cheap.selected_team}
    assert "codex_gpt5" in balanced_models          # balanced keeps standard coder
    assert "kimi_coder_mock" in cheap_models           # cost flips to the local coder
    assert "claude_a_opus" not in cheap_models      # premium planner dropped


def test_performance_objective_keeps_premium(graph, analyzer):
    task = analyzer.analyze("이 python repo 버그 고쳐줘")
    perf = TeamFormer(graph, objective="performance").form(task)
    assert "claude_a_opus" in {m.model for m in perf.selected_team}


def test_advisor_cost_objective_uses_recorded_cost():
    # moderate history so the base bonus stays below BONUS_CAP and the
    # economy term is observable (a saturated cap would mask it)
    stats = {
        ("cheap_m", "coding"): {"attempts": 4, "successes": 2, "average_confidence": 0.6,
                                "average_cost": 0.001, "average_tokens": 100},
        ("pricey_m", "coding"): {"attempts": 4, "successes": 2, "average_confidence": 0.6,
                                 "average_cost": 0.02, "average_tokens": 100},
    }
    adv = MemoryAdvisor(stats, {})
    base_cheap, _ = adv.bonus("cheap_m", "builder", "coding")
    cost_cheap, reasons = adv.bonus("cheap_m", "builder", "coding", objective="cost")
    cost_pricey, _ = adv.bonus("pricey_m", "builder", "coding", objective="cost")
    assert cost_cheap > base_cheap            # cost objective adds an economy term
    assert cost_cheap > cost_pricey           # cheaper history wins under cost objective
    assert any("cheap" in r for r in reasons)


# --- CLI ----------------------------------------------------------------------

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


def test_cli_run_reports_and_stores_economics(ammo_root, capsys):
    code = cli.main(["run", "--mock", "이 python repo 버그 고쳐줘"])
    out = capsys.readouterr().out
    assert code == 0 and "economics:" in out and "tokens" in out
    run_id = next(l.split("run_id: ", 1)[1].strip() for l in out.splitlines() if l.startswith("run_id: "))
    summary = json.loads(
        (ammo_root / "runtime" / "runs" / run_id / "run_summary.json").read_text(encoding="utf-8")
    )
    assert summary["economics"]["total_tokens"] > 0
    assert summary["economics"]["model_count"] == len(summary["team"])


def test_cli_efficiency_report(ammo_root, capsys):
    cli.main(["run", "--mock", "이 python repo 버그 고쳐줘"])
    capsys.readouterr()
    code = cli.main(["efficiency", "--system", "coding"])
    out = capsys.readouterr().out
    assert code == 0
    assert "Model efficiency" in out and "codex_gpt5" in out
    assert "Team combinations" in out


def test_cli_pricing_show(ammo_root, capsys):
    code = cli.main(["pricing"])
    out = capsys.readouterr().out
    assert code == 0 and "claude_a_opus" in out and "subscription" in out
