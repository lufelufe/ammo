"""Tests for `ammo dream` — automated memory consolidation."""

import json
import os
import shutil
from pathlib import Path

import pytest

from ammo import cli
from ammo.dream import DreamEngine
from ammo.memory import MemoryStore

REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def root(tmp_path):
    r = tmp_path / "root"
    r.mkdir()
    os.symlink(REPO_ROOT / "registry", r / "registry")
    shutil.copytree(REPO_ROOT / "systems", r / "systems")
    for name in ("runtime", "memory", "vaults"):
        (r / name).mkdir()
    (r / "runtime" / "runs").mkdir()
    return r


def _seed(root):
    """6 stale ghost runs + 1 legacy-tagged run + 4 recent good runs."""
    with MemoryStore.open(root) as s:
        for i in range(6):
            s.record_run(run_id=f"old{i}", timestamp=f"2026-01-0{i+1}", domain="coding",
                         tags=[], selected_system="coding", model_ids=["ghost_model"],
                         team_signature="builder:ghost_model", confidence_score=0.9)
        s.record_run(run_id="legacy1", timestamp="2026-02-01", domain="investment",
                     tags=[], selected_system="personal", model_ids=["claude_a_opus"],
                     team_signature="researcher:claude_a_opus", confidence_score=0.7)
        for i in range(4):
            s.record_run(run_id=f"new{i}", timestamp=f"2026-07-0{i+1}", domain="coding",
                         tags=[], selected_system="coding", model_ids=["kimi_coder_mock"],
                         team_signature="builder:kimi_coder_mock", confidence_score=0.8,
                         model_usage={"kimi_coder_mock": {"tokens": 500, "cost": 0.001}})
    for rid in ["old0", "old1", "new0", "new1", "new2", "new3", "legacy1"]:
        (root / "runtime" / "runs" / rid).mkdir()


def _seed_journal(root, entries=30):
    role_dir = root / "systems" / "coding" / "roles" / "builder"
    # exist_ok: the `root` fixture copies the live systems/ tree, which may
    # already carry a gitignored roles/builder/ from a prior real run.
    role_dir.mkdir(parents=True, exist_ok=True)
    with (role_dir / "journal.jsonl").open("w", encoding="utf-8") as fh:
        for i in range(entries):
            fh.write(json.dumps({"run_id": f"r{i}", "timestamp": f"t{i}",
                                 "model": "kimi_coder_mock", "output": f"work {i}"}) + "\n")
    return role_dir


# --- dry-run ------------------------------------------------------------------

def test_plan_reports_without_mutating(root):
    _seed(root)
    report = DreamEngine(root, window=5).plan()
    assert report.applied is False
    assert report.runs_total == 11
    assert "ghost_model@coding" in report.orphan_model_rows
    assert report.orphan_team_rows == 1
    assert len(report.runs_pruned) == 6
    assert set(report.run_dirs_pruned) == {"old0", "old1"}
    # nothing changed
    with MemoryStore.open(root) as s:
        assert s.stats()["total_runs"] == 11
        assert any(r["model_id"] == "ghost_model" for r in s.all_model_performance())


def test_plan_without_db_is_graceful(root):
    report = DreamEngine(root).plan()
    assert report.runs_total == 0
    assert any("no memory db" in n for n in report.notes)


# --- apply ----------------------------------------------------------------------

def test_apply_consolidates_everything(root):
    _seed(root)
    report = DreamEngine(root, window=5).apply()
    assert report.applied and report.backup.endswith(".bak")
    assert Path(report.backup).is_file()

    with MemoryStore.open(root) as s:
        perf = {(r["model_id"], r["task_tag"]): r for r in s.all_model_performance()}
        # orphan gone
        assert not any(m == "ghost_model" for m, _ in perf)
        # legacy domain tag merged into the system tag
        assert ("claude_a_opus", "personal") in perf
        assert not any(t == "investment" for _, t in perf)
        # window kept the 4 recent + 1 legacy run
        assert s.stats()["total_runs"] == 5
        # cost/token carry-over survived the rebuild
        assert perf[("kimi_coder_mock", "coding")]["average_tokens"] == 500.0
        teams = s.all_team_synergy()
        assert not any("ghost_model" in t["team_signature"] for t in teams)

    remaining_dirs = {p.name for p in (root / "runtime" / "runs").iterdir()}
    assert remaining_dirs == {"legacy1", "new0", "new1", "new2", "new3"}


def test_apply_distills_oversized_journal(root):
    role_dir = _seed_journal(root, entries=30)
    report = DreamEngine(root, journal_keep=20).apply()
    assert report.applied
    lines = [l for l in (role_dir / "journal.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
    assert len(lines) == 20
    insights = (role_dir / "insights.md").read_text(encoding="utf-8")
    assert "30 turn(s) seen" in insights and "kimi_coder_mock (30)" in insights
    # kept entries are the most recent ones
    assert json.loads(lines[-1])["run_id"] == "r29"


def test_small_journal_left_alone(root):
    role_dir = _seed_journal(root, entries=5)
    DreamEngine(root, journal_keep=20).apply()
    lines = (role_dir / "journal.jsonl").read_text(encoding="utf-8").splitlines()
    assert len([l for l in lines if l.strip()]) == 5
    assert not (role_dir / "insights.md").exists()


def test_apply_is_idempotent(root):
    _seed(root)
    DreamEngine(root, window=5).apply()
    second = DreamEngine(root, window=5).apply()
    assert second.orphan_model_rows == [] and second.runs_pruned == []
    with MemoryStore.open(root) as s:
        assert s.stats()["total_runs"] == 5


# --- CLI ------------------------------------------------------------------------

@pytest.fixture
def ammo_root(root, monkeypatch):
    monkeypatch.setenv("AMMO_ROOT", str(root))
    return root


def test_cli_dream_dry_run_then_apply(ammo_root, capsys):
    _seed(ammo_root)
    assert cli.main(["dream", "--window", "5"]) == 0
    out = capsys.readouterr().out
    assert "DRY-RUN" in out and "ghost_model@coding" in out

    assert cli.main(["dream", "--window", "5", "--apply"]) == 0
    out = capsys.readouterr().out
    assert "APPLIED" in out and "backup:" in out


def test_doctor_suggests_dream_when_memory_bloats(root):
    from ammo.doctor import run_doctor

    with MemoryStore.open(root) as s:
        for i in range(55):   # > DEFAULT_WINDOW (50)
            s.record_run(run_id=f"b{i}", timestamp=f"t{i}", domain="coding", tags=[],
                         selected_system="coding", model_ids=["kimi_coder_mock"],
                         team_signature="builder:kimi_coder_mock", confidence_score=0.7)
    report = run_doctor(root)
    assert any("ammo dream" in n for n in report.notices)


def test_doctor_quiet_below_window(root):
    from ammo.doctor import run_doctor

    with MemoryStore.open(root) as s:
        s.record_run(run_id="one", timestamp="t", domain="coding", tags=[],
                     selected_system="coding", model_ids=["kimi_coder_mock"],
                     team_signature="builder:kimi_coder_mock", confidence_score=0.7)
    report = run_doctor(root)
    assert not any("ammo dream" in n for n in report.notices)


def test_orphan_sandboxes_are_pruned_referenced_kept(root):
    _seed(root)
    sandbox_root = root / "runtime" / "sandbox"
    (sandbox_root / "keepme").mkdir(parents=True)
    (sandbox_root / "orphan1").mkdir()
    # newest run (new3, inside window 5) references "keepme"
    summary = root / "runtime" / "runs" / "new3" / "run_summary.json"
    summary.write_text(json.dumps({"run_id": "new3",
                                   "sandbox": str(sandbox_root / "keepme")}),
                       encoding="utf-8")
    report = DreamEngine(root, window=5).apply()
    assert "orphan1" in report.sandboxes_pruned
    assert not (sandbox_root / "orphan1").exists()
    assert (sandbox_root / "keepme").is_dir()          # referenced -> survives


def test_insights_name_the_best_model_for_the_seat(root):
    # journal turns cross-referenced with run confidences -> per-model quality
    role_dir = root / "systems" / "coding" / "roles" / "builder"
    role_dir.mkdir(parents=True, exist_ok=True)  # tolerate a copied prior-run dir
    with MemoryStore.open(root) as s:
        for i in range(30):
            model = "codex_gpt5" if i % 2 else "kimi_coder_mock"
            conf = 0.9 if model == "codex_gpt5" else 0.3
            s.record_run(run_id=f"j{i}", timestamp=f"t{i:02d}", domain="coding", tags=[],
                         selected_system="coding", model_ids=[model],
                         team_signature=f"builder:{model}", confidence_score=conf)
    with (role_dir / "journal.jsonl").open("w", encoding="utf-8") as fh:
        for i in range(30):
            model = "codex_gpt5" if i % 2 else "kimi_coder_mock"
            fh.write(json.dumps({"run_id": f"j{i}", "timestamp": f"t{i:02d}",
                                 "model": model, "output": f"work {i}"}) + "\n")

    DreamEngine(root, journal_keep=20).apply()
    insights = (role_dir / "insights.md").read_text(encoding="utf-8")
    assert "best for this seat so far: codex_gpt5" in insights
    assert "avg confidence 0.90" in insights
    assert "kimi_coder_mock: avg confidence 0.30" in insights
