"""Tests for Memory Feedback v0 (Milestone 10)."""

import os
import shutil
from pathlib import Path

import pytest

from ammo import cli
from ammo.memory import MemoryStore, outcome_from_confidence, team_signature
from ammo.kernel.team_formation.execution_plan import ExecutionPlan, TeamMember

REPO_ROOT = Path(__file__).resolve().parents[1]
TS = "2026-07-01T12:00:00+00:00"


def _record(store, run_id, domain, models, conf, tags=None):
    store.record_run(
        run_id=run_id, timestamp=TS, domain=domain, tags=tags or [],
        selected_system=domain, model_ids=models,
        team_signature="+".join(sorted(models)), confidence_score=conf,
    )


# --- schema & basic recording ----------------------------------------------

def test_schema_created(tmp_path):
    store = MemoryStore(tmp_path / "m.sqlite")
    names = {r["name"] for r in store.conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    )}
    assert {"runs", "model_performance", "team_synergy"} <= names
    store.close()


def test_record_run_populates_all_tables(tmp_path):
    store = MemoryStore(tmp_path / "m.sqlite")
    _record(store, "r1", "coding", ["codex_gpt5", "claude_b_fable"], 0.8)
    stats = store.stats()
    assert stats["total_runs"] == 1
    assert stats["by_domain"] == {"coding": 1}
    assert {m["model_id"] for m in stats["models"]} == {"codex_gpt5", "claude_b_fable"}
    assert len(stats["teams"]) == 1
    store.close()


def test_running_average_and_success_counters(tmp_path):
    store = MemoryStore(tmp_path / "m.sqlite")
    _record(store, "r1", "coding", ["codex_gpt5"], 0.6)
    _record(store, "r2", "coding", ["codex_gpt5"], 0.8)
    perf = next(m for m in store.stats()["models"] if m["model_id"] == "codex_gpt5")
    assert perf["attempts"] == 2
    assert perf["successes"] == 2          # both >= 0.5
    assert perf["average_confidence"] == 0.7
    store.close()


def test_low_confidence_counts_as_non_success(tmp_path):
    store = MemoryStore(tmp_path / "m.sqlite")
    _record(store, "r1", "coding", ["kimi_coder_mock"], 0.2)
    perf = store.stats()["models"][0]
    assert perf["attempts"] == 1 and perf["successes"] == 0
    store.close()


def test_migration_backfills_missing_column(tmp_path):
    import sqlite3

    db = tmp_path / "old.sqlite"
    # an OLD runs table created before the team_signature column existed
    conn = sqlite3.connect(str(db))
    conn.executescript(
        "CREATE TABLE runs (run_id TEXT PRIMARY KEY, timestamp TEXT, domain TEXT, "
        "tags TEXT, selected_system TEXT, selected_models TEXT, confidence_score REAL, "
        "outcome_status TEXT, user_feedback TEXT);"
    )
    conn.commit()
    conn.close()

    store = MemoryStore(db)  # opening must migrate, not crash
    cols = {r["name"] for r in store.conn.execute("PRAGMA table_info(runs)")}
    assert "team_signature" in cols
    # and the new features work against the migrated DB
    store.record_run(run_id="r1", timestamp="t", domain="coding", tags=[],
                     selected_system="coding", model_ids=["m"], team_signature="sig",
                     confidence_score=0.8)
    assert store.best_team_for_system("coding")["team_signature"] == "sig"
    store.close()


def test_outcome_mapping():
    assert outcome_from_confidence(0.9) == "success"
    assert outcome_from_confidence(0.6) == "acceptable"
    assert outcome_from_confidence(0.3) == "weak"
    assert outcome_from_confidence(0.1) == "failed"


def test_list_runs_ordered_desc(tmp_path):
    store = MemoryStore(tmp_path / "m.sqlite")
    store.record_run(run_id="a", timestamp="2026-01-01T00:00:00+00:00", domain="coding",
                     tags=[], selected_system="coding", model_ids=["x"],
                     team_signature="x", confidence_score=0.7)
    store.record_run(run_id="b", timestamp="2026-02-01T00:00:00+00:00", domain="research",
                     tags=[], selected_system="research", model_ids=["y"],
                     team_signature="y", confidence_score=0.7)
    runs = store.list_runs()
    assert [r["run_id"] for r in runs] == ["b", "a"]  # newest first
    assert runs[0]["selected_models"] == ["y"]
    store.close()


def test_team_signature_is_stable():
    plan = ExecutionPlan(
        selected_system="coding",
        selected_team=[TeamMember("critic", "cB"), TeamMember("builder", "cx")],
        roles=["critic", "builder"],
    )
    assert team_signature(plan) == "builder:cx+critic:cB"


# --- CLI (temp AMMO root) ---------------------------------------------------

@pytest.fixture
def ammo_root(tmp_path, monkeypatch):
    root = tmp_path / "root"
    root.mkdir()
    os.symlink(REPO_ROOT / "registry", root / "registry")
    shutil.copytree(REPO_ROOT / "systems", root / "systems")  # copy: `run` writes role dirs
    for name in ("runtime", "memory", "vaults"):
        (root / name).mkdir()
    monkeypatch.setenv("AMMO_ROOT", str(root))
    return root


def test_cli_run_updates_memory_then_stats_and_runs(ammo_root, capsys):
    code = cli.main(["run", "--mock", "투자 리서치 검증해줘"])
    out = capsys.readouterr().out
    assert code == 0
    run_id = next(l.split("run_id: ", 1)[1].strip() for l in out.splitlines() if l.startswith("run_id: "))
    assert (ammo_root / "memory" / "ammo.sqlite").is_file()

    assert cli.main(["memory", "stats"]) == 0
    stats_out = capsys.readouterr().out
    assert "runs: 1" in stats_out

    assert cli.main(["memory", "runs"]) == 0
    runs_out = capsys.readouterr().out
    assert run_id in runs_out


def test_cli_memory_stats_empty(ammo_root, capsys):
    assert cli.main(["memory", "stats"]) == 0
    out = capsys.readouterr().out
    assert "runs: 0" in out
    assert "no runs recorded" in out
