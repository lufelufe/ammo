"""Tests for provider availability + CommandAdapter (Milestone 14)."""

from pathlib import Path

import pytest

from ammo import cli
from ammo.adapters import AdapterRequest, BaseModelAdapter, CommandAdapter
from ammo.providers import (
    DEFAULT_CATALOG,
    AvailabilityDetector,
    ProviderProfile,
    select_models,
)
from ammo.providers.profile import API, LOCAL, SUBSCRIPTION_CLI

REPO_ROOT = Path(__file__).resolve().parents[1]


def _detector(installed=(), authed=True, env=None, local_out=""):
    installed = set(installed)
    return AvailabilityDetector(
        which=lambda c: f"/bin/{c}" if c in installed else None,
        # auth checks are `claude auth status` / `codex login status` (verified
        # live); the local list command ends in "list".
        runner=lambda cmd, stdin="": (
            (0 if authed else 1, "") if "status" in cmd
            else (0, local_out) if cmd[-1] == "list"
            else (0, "")
        ),
        environ=env if env is not None else {},
    )


CLAUDE = next(p for p in DEFAULT_CATALOG if p.id == "claude-code")
OLLAMA = next(p for p in DEFAULT_CATALOG if p.id == "ollama")
ANTHROPIC = next(p for p in DEFAULT_CATALOG if p.id == "anthropic-api")


# --- subscription CLI -------------------------------------------------------

def test_cli_authenticated_available():
    st = _detector(installed={"claude"}, authed=True).detect(CLAUDE)
    assert st.available and st.detail == "authenticated"
    assert st.models == ["claude_a_planner", "claude_b_critic"]


def test_cli_installed_but_not_authenticated():
    st = _detector(installed={"claude"}, authed=False).detect(CLAUDE)
    assert not st.available and "not authenticated" in st.detail


def test_cli_not_installed():
    st = _detector(installed=set()).detect(CLAUDE)
    assert not st.available and st.detail == "not installed"


# --- API (presence only, no secrets) ---------------------------------------

def test_api_available_when_env_set_and_hides_value():
    st = _detector(env={"ANTHROPIC_API_KEY": "sk-secret-value"}).detect(ANTHROPIC)
    assert st.available
    assert "ANTHROPIC_API_KEY" in st.detail
    assert "sk-secret-value" not in st.detail  # never leak the value


def test_api_unavailable_when_unset():
    st = _detector(env={}).detect(ANTHROPIC)
    assert not st.available and "unset" in st.detail


# --- local ------------------------------------------------------------------

def test_local_lists_models():
    out = "NAME  ID\nqwen2.5-coder:7b  a\nllama3:8b  b\n"
    st = _detector(installed={"ollama"}, local_out=out).detect(OLLAMA)
    assert st.available and st.models == ["qwen2.5-coder:7b", "llama3:8b"]


def test_local_not_installed():
    st = _detector(installed=set()).detect(OLLAMA)
    assert not st.available


# --- cost policy ------------------------------------------------------------

def test_select_prefers_included_over_paid():
    det = _detector(installed={"claude"}, authed=True, env={"ANTHROPIC_API_KEY": "x"})
    statuses = det.detect_all(DEFAULT_CATALOG)
    usable = select_models(statuses)  # allow_paid=False
    # claude models come from the subscription CLI, not the paid API
    assert usable["claude_a_planner"] == "claude-code"


def test_paid_only_model_excluded_unless_allowed():
    det = _detector(installed=set(), env={"OPENAI_API_KEY": "x"})
    statuses = det.detect_all(DEFAULT_CATALOG)
    assert "codex_builder" not in select_models(statuses)                       # paid skipped
    assert select_models(statuses, allow_paid=True)["codex_builder"] == "openai-api"


# --- CommandAdapter ---------------------------------------------------------

def test_command_adapter_wraps_output_and_does_not_self_confidence():
    a = CommandAdapter("m", ["claude", "-p"], runner=lambda cmd, stdin="": (0, f"OUT:{stdin}"))
    assert isinstance(a, BaseModelAdapter)
    resp = a.execute(AdapterRequest(role="planner", model="m", task_input="do x"))
    assert "do x" in resp.output
    assert resp.confidence == 0.0           # evidence-based confidence, not self-reported
    assert a.describe()["kind"] == "command"


def test_command_adapter_handles_nonzero_exit():
    a = CommandAdapter("m", ["broken"], runner=lambda cmd, stdin="": (2, ""))
    resp = a.execute(AdapterRequest(role="x", model="m", task_input="t"))
    assert "exited 2" in resp.output


# --- CLI --------------------------------------------------------------------

def test_cli_providers_runs(monkeypatch, capsys):
    monkeypatch.setenv("AMMO_ROOT", str(REPO_ROOT))
    code = cli.main(["providers"])
    out = capsys.readouterr().out
    assert code == 0
    assert "Providers:" in out
