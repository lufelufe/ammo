"""Tests for per-system model binding + selection wizard (Milestone 15)."""

import os
import shutil
import sys
from pathlib import Path

import pytest

from ammo import cli
from ammo.binding import Binding, BindingStore, build_binding, existing_or_best
from ammo.binding.wizard import available_choices
from ammo.kernel.capability_graph import CapabilityGraph
from ammo.kernel.task_understanding import TaskAnalyzer
from ammo.kernel.team_formation import TeamFormer
from ammo.memory import MemoryStore
from ammo.providers.profile import ProviderProfile, ProviderStatus

REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def root(tmp_path):
    r = tmp_path / "root"
    r.mkdir()
    os.symlink(REPO_ROOT / "registry", r / "registry")
    shutil.copytree(REPO_ROOT / "systems", r / "systems")
    for name in ("runtime", "memory", "vaults"):
        (r / name).mkdir()
    return r


# --- Binding data + store ---------------------------------------------------

def test_binding_helpers_and_roundtrip(root):
    b = Binding("coding", models=[{"id": "m1", "provider": "p"}],
                team=[{"role": "builder", "model": "m1"}])
    assert b.model_ids == ["m1"]
    assert b.team_map == {"builder": "m1"}
    store = BindingStore(root)
    store.save(b)
    assert store.exists("coding")
    loaded = store.load("coding")
    assert loaded.model_ids == ["m1"] and loaded.team_map == {"builder": "m1"}


# --- wizard decision logic --------------------------------------------------

def test_existing_or_best_prefers_existing_binding(root):
    BindingStore(root).save(Binding("coding", models=[{"id": "x", "provider": "p"}]))
    proposal = existing_or_best(root, "coding")
    assert proposal["source"] == "existing_binding"


def test_existing_or_best_falls_back_to_memory(root):
    with MemoryStore.open(root) as mem:
        for i in range(3):
            mem.record_run(run_id=f"r{i}", timestamp=f"2026-01-0{i+1}", domain="coding", tags=[],
                           selected_system="coding", model_ids=["kimi_coder_mock", "claude_b_fable"],
                           team_signature="builder:kimi_coder_mock+critic:claude_b_fable",
                           confidence_score=0.8)
    proposal = existing_or_best(root, "coding")
    assert proposal["source"] == "memory_best"
    assert proposal["binding"].team_map == {"builder": "kimi_coder_mock", "critic": "claude_b_fable"}


def test_existing_or_best_none_when_empty(root):
    assert existing_or_best(root, "coding") is None


def test_available_choices_from_statuses():
    prof = ProviderProfile("claude-code", "subscription_cli", "Claude Code",
                           models=["claude_a_opus"], cost="included")
    statuses = [ProviderStatus(prof, True, "authenticated", ["claude_a_opus"])]
    choices = available_choices(statuses)
    assert choices == [{"model": "claude_a_opus", "provider": "claude-code",
                        "kind": "subscription_cli"}]


# --- memory: best team for a system ----------------------------------------

def test_best_team_for_system_ranks_by_success(root):
    with MemoryStore.open(root) as mem:
        for i in range(2):  # team A: 2 runs, both weak
            mem.record_run(run_id=f"a{i}", timestamp="2026-01-01", domain="coding", tags=[],
                           selected_system="coding", model_ids=["m"], team_signature="A",
                           confidence_score=0.2)
        for i in range(2):  # team B: 2 runs, both strong
            mem.record_run(run_id=f"b{i}", timestamp="2026-01-02", domain="coding", tags=[],
                           selected_system="coding", model_ids=["m"], team_signature="B",
                           confidence_score=0.9)
        best = mem.best_team_for_system("coding")
    assert best["team_signature"] == "B"
    assert best["successes"] == 2


# --- TeamFormer honors binding ---------------------------------------------

@pytest.fixture(scope="module")
def graph():
    return CapabilityGraph.from_registry(root=REPO_ROOT)


@pytest.fixture(scope="module")
def analyzer():
    return TaskAnalyzer(systems=[])


def test_bound_team_pins_role(graph, analyzer):
    task = analyzer.analyze("이 python repo 버그 고쳐줘")  # coding_high_risk -> builder seat
    binding = Binding("coding", team=[{"role": "builder", "model": "kimi_coder_mock"}])
    plan = TeamFormer(graph, binding=binding).form(task)
    builder = next(m.model for m in plan.selected_team if m.role == "builder")
    assert builder == "kimi_coder_mock"


def test_binding_restricts_model_set(graph, analyzer):
    task = analyzer.analyze("이 python repo 버그 고쳐줘")
    # allowed set excludes codex_gpt5 -> builder must come from the bound set
    binding = Binding("coding", models=[{"id": m, "provider": "p"} for m in
                                        ["kimi_coder_mock", "claude_a_opus", "claude_b_fable"]])
    plan = TeamFormer(graph, binding=binding).form(task)
    picked = {m.model for m in plan.selected_team if m.role != "test_runner"}
    assert "codex_gpt5" not in picked
    assert "kimi_coder_mock" in {m.model for m in plan.selected_team}


def test_no_binding_matches_default(graph, analyzer):
    task = analyzer.analyze("이 python repo 버그 고쳐줘")
    a = [m.to_dict() for m in TeamFormer(graph).form(task).selected_team]
    b = [m.to_dict() for m in TeamFormer(graph, binding=None).form(task).selected_team]
    assert a == b


# --- CLI --------------------------------------------------------------------

@pytest.fixture
def ammo_root(root, monkeypatch):
    monkeypatch.setenv("AMMO_ROOT", str(root))
    return root


def test_cli_bind_models_then_run_uses_binding(ammo_root, capsys):
    code = cli.main(["bind", "coding", "--models",
                     "kimi_coder_mock,claude_a_opus,claude_b_fable,local_test_runner"])
    out = capsys.readouterr().out
    assert code == 0 and "Bound 'coding'" in out
    assert (ammo_root / "systems" / "coding" / ".ammo" / "binding.yaml").is_file()

    import json
    cli.main(["plan-team", "이 python repo 버그 고쳐줘"])
    plan = json.loads(capsys.readouterr().out)
    builder = next(m["model"] for m in plan["selected_team"] if m["role"] == "builder")
    assert builder == "kimi_coder_mock"  # codex excluded by the binding


def test_cli_bind_reuse_flag(ammo_root, capsys):
    cli.main(["bind", "coding", "--models", "kimi_coder_mock"])
    capsys.readouterr()
    code = cli.main(["bind", "coding", "--reuse"])
    out = capsys.readouterr().out
    assert code == 0 and "reused existing_binding" in out


def test_cli_bind_unknown_system(ammo_root, capsys):
    code = cli.main(["bind", "ghost", "--models", "m"])
    out = capsys.readouterr().out
    assert code == 1 and "no system pack" in out


def test_cli_bind_non_tty_no_flags_errors(ammo_root, monkeypatch, capsys):
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
    code = cli.main(["bind", "research"])  # no binding, no memory, no --models
    out = capsys.readouterr().out
    assert code == 2 and "--models" in out
