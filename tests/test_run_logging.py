"""Tests for Execution Graph + Run Logging (Milestone 8).

Run persistence is exercised against a temporary AMMO root (registry/systems are
symlinked from the repo) so runs are never written into the real repo tree.
"""

import json
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path

import pytest

from ammo import cli
from ammo.adapters import MockAdapter
from ammo.kernel.capability_graph import CapabilityGraph
from ammo.kernel.executor import RUN_FILES, ExecutionGraph, Runner, RunStore
from ammo.kernel.task_understanding import TaskAnalyzer
from ammo.kernel.team_formation import TeamFormer

REPO_ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 7, 1, 12, 0, 0, tzinfo=timezone.utc)


@pytest.fixture(scope="module")
def graph():
    return CapabilityGraph.from_registry(root=REPO_ROOT)


@pytest.fixture(scope="module")
def analyzer():
    return TaskAnalyzer(systems=[])


def _run(analyzer, graph, prompt):
    task = analyzer.analyze(prompt)
    plan = TeamFormer(graph).form(task)
    result = Runner(lambda mid: MockAdapter(mid)).run(plan, task)
    return task, plan, result


@pytest.fixture
def ammo_root(tmp_path, monkeypatch):
    """A temp AMMO root: registry/systems symlinked, empty runtime/memory/vaults."""
    root = tmp_path / "root"
    root.mkdir()
    os.symlink(REPO_ROOT / "registry", root / "registry")
    shutil.copytree(REPO_ROOT / "systems", root / "systems")  # copy: `run` writes role dirs
    for name in ("runtime", "memory", "vaults"):
        (root / name).mkdir()
    monkeypatch.setenv("AMMO_ROOT", str(root))
    return root


# --- execution graph --------------------------------------------------------

def test_execution_graph_from_plan_is_ordered(analyzer, graph):
    _, plan, _ = _run(analyzer, graph, "이 Python repo 버그 고치고 테스트 추가해줘")
    eg = ExecutionGraph.from_plan(plan)
    assert [s.order for s in eg.steps] == list(range(len(plan.selected_team)))
    assert [s.role for s in eg.steps] == plan.roles
    assert [s.model for s in eg.steps] == [m.model for m in plan.selected_team]


# --- run store --------------------------------------------------------------

def test_save_writes_all_run_files(tmp_path, analyzer, graph):
    task, plan, result = _run(analyzer, graph, "이 회사 투자 리서치 검증해줘")
    store = RunStore(tmp_path)
    run_id, path = store.save(
        input_text="이 회사 투자 리서치 검증해줘",
        task=task, plan=plan, result=result, run_id="testrun-1", now=NOW,
    )
    assert run_id == "testrun-1"
    assert path == tmp_path / "runtime" / "runs" / "testrun-1"
    for name in RUN_FILES:
        assert (path / name).is_file(), name
    # each json artifact parses
    for name in RUN_FILES:
        if name.endswith(".json"):
            json.loads((path / name).read_text(encoding="utf-8"))
    # markdown carries the request
    assert "이 회사 투자 리서치 검증해줘" in (path / "final_output.md").read_text(encoding="utf-8")


def test_run_summary_and_input_contents(tmp_path, analyzer, graph):
    task, plan, result = _run(analyzer, graph, "오늘 할 일 정리해줘")
    store = RunStore(tmp_path)
    _, path = store.save(input_text="오늘 할 일 정리해줘", task=task, plan=plan,
                         result=result, run_id="r2", now=NOW)
    summary = json.loads((path / "run_summary.json").read_text(encoding="utf-8"))
    assert summary["run_id"] == "r2"
    assert summary["created_at"] == NOW.isoformat()
    assert summary["selected_system"] == "personal"
    assert summary["mode"] == "mock"
    assert "self_reported_mean" in summary
    inp = json.loads((path / "input.json").read_text(encoding="utf-8"))
    assert inp["input"] == "오늘 할 일 정리해줘"


def test_load_summary_and_missing(tmp_path, analyzer, graph):
    task, plan, result = _run(analyzer, graph, "오늘 할 일 정리해줘")
    store = RunStore(tmp_path)
    store.save(input_text="x", task=task, plan=plan, result=result, run_id="r3", now=NOW)
    assert store.load_summary("r3")["run_id"] == "r3"
    with pytest.raises(FileNotFoundError):
        store.load_summary("nope")


def test_save_is_deterministic_given_fixed_id_and_time(tmp_path, analyzer, graph):
    task, plan, result = _run(analyzer, graph, "이 주제 자료 조사하고 근거 검증해줘")
    a = RunStore(tmp_path / "a")
    b = RunStore(tmp_path / "b")
    _, pa = a.save(input_text="x", task=task, plan=plan, result=result, run_id="r", now=NOW)
    _, pb = b.save(input_text="x", task=task, plan=plan, result=result, run_id="r", now=NOW)
    for name in RUN_FILES:
        assert (pa / name).read_text(encoding="utf-8") == (pb / name).read_text(encoding="utf-8")


def test_list_runs(tmp_path, analyzer, graph):
    task, plan, result = _run(analyzer, graph, "오늘 할 일 정리해줘")
    store = RunStore(tmp_path)
    store.save(input_text="x", task=task, plan=plan, result=result, run_id="rb", now=NOW)
    store.save(input_text="x", task=task, plan=plan, result=result, run_id="ra", now=NOW)
    assert store.list_runs() == ["ra", "rb"]


# --- CLI: run + show-run ----------------------------------------------------

def _extract_run_id(stdout: str) -> str:
    for line in stdout.splitlines():
        if line.startswith("run_id: "):
            return line.split("run_id: ", 1)[1].strip()
    raise AssertionError(f"no run_id in output:\n{stdout}")


def test_cli_run_then_show_run(ammo_root, capsys):
    code = cli.main(["run", "--mock", "Qwen과 Kimi 중 코딩에 뭐가 나은지 분석해줘"])
    out = capsys.readouterr().out
    assert code == 0
    assert "run_id: " in out and "output: " in out
    run_id = _extract_run_id(out)

    run_dir = ammo_root / "runtime" / "runs" / run_id
    assert run_dir.is_dir()
    for name in RUN_FILES:
        assert (run_dir / name).is_file(), name

    code2 = cli.main(["show-run", run_id])
    out2 = capsys.readouterr().out
    assert code2 == 0
    data = json.loads(out2)
    assert data["run_id"] == run_id
    assert data["selected_system"] == "coding"


def test_cli_show_run_unknown(ammo_root, capsys):
    code = cli.main(["show-run", "does-not-exist"])
    out = capsys.readouterr().out
    assert code == 1
    assert "not found" in out
