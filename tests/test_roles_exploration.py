"""Tests for role working dirs + per-system memory + exploration (Milestone 16)."""

import json
import os
import shutil
from pathlib import Path

import pytest

from ammo import cli
from ammo.memory import MemoryAdvisor, MemoryStore
from ammo.roles import RoleWorkspace

REPO_ROOT = Path(__file__).resolve().parents[1]


# --- role-bound working directories -----------------------------------------

def test_workspace_binds_traces_to_role_not_model(tmp_path):
    ws = RoleWorkspace(tmp_path)
    ws.record("coding", "builder", run_id="r1", model="codex_gpt5", output="did x",
              evidence=[{"kind": "diff"}], timestamp="t1")
    ws.record("coding", "builder", run_id="r2", model="kimi_coder_mock", output="did y",
              timestamp="t2")  # SAME role, DIFFERENT model
    journal = ws.journal("coding", "builder")
    assert [e["model"] for e in journal] == ["codex_gpt5", "kimi_coder_mock"]
    assert journal[0]["output"] == "did x"
    assert ws.roles("coding") == ["builder"]
    assert (ws.path("coding", "builder") / "last.md").is_file()


def test_workspace_path_is_per_system_per_role(tmp_path):
    ws = RoleWorkspace(tmp_path)
    p = ws.path("research", "critic")
    assert p == tmp_path / "systems" / "research" / "roles" / "critic"


# --- per-system performance memory ------------------------------------------

def test_memory_is_keyed_by_system_not_domain(tmp_path):
    with MemoryStore(tmp_path / "m.sqlite") as mem:
        # domain "coding" but a distinct connected system "myproj"
        mem.record_run(run_id="r1", timestamp="t", domain="coding", tags=[],
                       selected_system="myproj", model_ids=["m"], team_signature="s",
                       confidence_score=0.8)
        perf = mem.stats()["models"][0]
    assert perf["task_tag"] == "myproj"  # attributed to the system, not the domain


# --- exploration ------------------------------------------------------------

def test_no_explore_gives_untried_model_no_bonus():
    adv = MemoryAdvisor({}, {}, explore=0.0)
    assert adv.bonus("m", "builder", "coding") == (0.0, [])


def test_explore_nudges_untried_model():
    adv = MemoryAdvisor({}, {}, explore=1.0)
    bonus, reasons = adv.bonus("m", "builder", "coding")
    assert bonus > 0 and any("under-explored" in r for r in reasons)


def test_explore_does_not_override_established_history():
    # a well-attested model uses its history term, not the exploration branch
    stats = {("m", "coding"): {"attempts": 4, "successes": 4, "average_confidence": 0.8}}
    adv = MemoryAdvisor(stats, {}, explore=1.0)
    bonus, reasons = adv.bonus("m", "builder", "coding")
    assert bonus > 0 and not any("under-explored" in r for r in reasons)


# --- CLI --------------------------------------------------------------------

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


def test_cli_run_writes_role_workspaces_then_role_log(ammo_root, capsys):
    cli.main(["run", "--mock", "이 python repo 버그 고쳐줘"])
    capsys.readouterr()
    builder_journal = ammo_root / "systems" / "coding" / "roles" / "builder" / "journal.jsonl"
    assert builder_journal.is_file()

    assert cli.main(["role-log", "coding", "builder"]) == 0
    out = capsys.readouterr().out
    assert "Role 'builder' in 'coding'" in out


def test_cli_explore_surfaces_untried_models(ammo_root, capsys):
    # build history for the default team, so untried models become distinguishable
    for _ in range(2):
        cli.main(["run", "--mock", "이 python repo 버그 고쳐줘"])
        capsys.readouterr()
    cli.main(["plan-team", "이 python repo 버그 고쳐줘", "--explore", "5"])
    plan = json.loads(capsys.readouterr().out)
    assert any("under-explored" in n for n in plan["notes"])
