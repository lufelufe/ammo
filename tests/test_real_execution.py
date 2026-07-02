"""Tests for real execution — resolve models to authenticated CLIs (M: real).

No real CLI is ever called: availability and command invocation are injected
(fake statuses + fake runner), so the whole real path is deterministic offline.
"""

import os
import shutil
from pathlib import Path

import pytest

from ammo import cli
from ammo.adapters import CommandAdapter, MockAdapter, RealAdapterFactory
from ammo.kernel.capability_graph import CapabilityGraph
from ammo.kernel.executor import Runner
from ammo.kernel.task_understanding import TaskAnalyzer
from ammo.kernel.team_formation import TeamFormer
from ammo.providers.profile import ProviderProfile, ProviderStatus

REPO_ROOT = Path(__file__).resolve().parents[1]

_CLAUDE = ProviderProfile("claude-code", "subscription_cli", "Claude Code",
                          invoke=["claude", "-p"],
                          models=["claude_a_planner", "claude_b_critic"], cost="included")
_OLLAMA = ProviderProfile("ollama", "local", "Ollama", invoke=["ollama", "run", "{model}"],
                          cost="included")
_API = ProviderProfile("anthropic-api", "api", "Anthropic API", env_var="ANTHROPIC_API_KEY",
                       invoke=None, models=["claude_a_planner"], cost="paid")


def _fake_runner(cmd, stdin=""):
    return 0, f"[{cmd[0]}] {stdin.splitlines()[0] if stdin else ''}"


# --- resolution -------------------------------------------------------------

def test_available_model_resolves_to_command_adapter():
    statuses = [ProviderStatus(_CLAUDE, True, "authenticated", ["claude_a_planner", "claude_b_critic"])]
    factory = RealAdapterFactory(statuses=statuses, runner=_fake_runner)
    adapter = factory("claude_a_planner")
    assert isinstance(adapter, CommandAdapter)
    assert factory.resolutions["claude_a_planner"] == ("real", "claude-code")


def test_unavailable_model_falls_back_to_mock():
    statuses = [ProviderStatus(_CLAUDE, True, "ok", ["claude_a_planner", "claude_b_critic"])]
    factory = RealAdapterFactory(statuses=statuses, runner=_fake_runner)
    adapter = factory("codex_builder")  # no provider offers it here
    assert isinstance(adapter, MockAdapter)
    assert factory.resolutions["codex_builder"] == ("mock", None)


def test_local_model_substitutes_placeholder():
    statuses = [ProviderStatus(_OLLAMA, True, "2 local", ["qwen2.5-coder:7b"])]
    factory = RealAdapterFactory(statuses=statuses, runner=_fake_runner)
    adapter = factory("qwen2.5-coder:7b")
    assert isinstance(adapter, CommandAdapter)
    assert adapter._command == ["ollama", "run", "qwen2.5-coder:7b"]


def test_api_provider_has_no_command_so_falls_back():
    # available but cost=paid and no invoke -> not a command route
    statuses = [ProviderStatus(_API, True, "key set", ["claude_a_planner"])]
    factory = RealAdapterFactory(statuses=statuses, runner=_fake_runner, allow_paid=True)
    assert isinstance(factory("claude_a_planner"), MockAdapter)


# --- full pipeline (mode=real) ---------------------------------------------

@pytest.fixture(scope="module")
def graph():
    return CapabilityGraph.from_registry(root=REPO_ROOT)


def test_real_run_marks_mode_and_mixes_real_and_mock(graph):
    statuses = [ProviderStatus(_CLAUDE, True, "ok", ["claude_a_planner", "claude_b_critic"])]
    factory = RealAdapterFactory(statuses=statuses, runner=_fake_runner)
    task = TaskAnalyzer(systems=[]).analyze("이 python repo 버그 고쳐줘")
    plan = TeamFormer(graph).form(task)
    result = Runner(factory, mode="real").run(plan, task)

    assert result.mode == "real"
    assert factory.real_count >= 1
    real_outputs = [r.output for r in result.responses if r.output.startswith("[claude]")]
    assert real_outputs  # at least one member answered via the (fake) CLI


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


def test_cli_run_requires_a_mode(ammo_root, capsys):
    code = cli.main(["run", "some request"])
    out = capsys.readouterr().out
    assert code == 2 and "mock" in out.lower() and "real" in out.lower()


def test_cli_run_rejects_both_modes(ammo_root, capsys):
    code = cli.main(["run", "--mock", "--real", "x"])
    out = capsys.readouterr().out
    assert code == 2 and "not both" in out


def test_cli_run_real_offline(ammo_root, monkeypatch, capsys):
    # make providers detectable + invocation deterministic without real CLIs
    import shutil as _sh
    monkeypatch.setattr(_sh, "which", lambda c: f"/bin/{c}" if c == "claude" else None)
    monkeypatch.setattr("ammo.providers.detector.default_runner",
                        lambda cmd, stdin="": (0, f"[{cmd[0]}] ok"))
    code = cli.main(["run", "--real", "이 python repo 버그 고쳐줘"])
    out = capsys.readouterr().out
    assert code == 0
    assert "mode: real" in out
    assert "adapters:" in out  # real/mock resolution reported
