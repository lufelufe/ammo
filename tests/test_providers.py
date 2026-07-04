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
        runner=lambda cmd, stdin="", env=None: (
            # auth probes now also require the expected marker in stdout
            ((0, '{"loggedIn": true} Logged in') if authed else (1, ""))
            if "status" in cmd
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
    assert st.models == ["claude_a_opus", "claude_b_fable",
                         "claude_a_haiku", "claude_a_sonnet"]


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
    assert usable["claude_a_opus"] == "claude-code"


def test_paid_only_model_excluded_unless_allowed():
    det = _detector(installed=set(), env={"OPENAI_API_KEY": "x"})
    statuses = det.detect_all(DEFAULT_CATALOG)
    assert "codex_gpt5" not in select_models(statuses)                       # paid skipped
    assert select_models(statuses, allow_paid=True)["codex_gpt5"] == "openai-api"


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


def test_model_args_extend_the_invoke_command():
    from ammo.adapters.resolver import _invoke_command

    claude = next(p for p in DEFAULT_CATALOG if p.id == "claude-code")
    haiku_cmd = _invoke_command(claude, "claude_a_haiku")
    default_cmd = _invoke_command(claude, "claude_a_opus")
    assert haiku_cmd[-2:] == ["--model", "haiku"]      # per-model CLI mapping
    assert "--model" not in default_cmd                # default seat untouched


# --- second Claude account slot (CLAUDE_CONFIG_DIR) --------------------------------

CLAUDE_B = next(p for p in DEFAULT_CATALOG if p.id == "claude-code-b")


def _two_account_detector(b_logged_in):
    """Fake: account A always logged in; account B per flag (keyed on env)."""
    def runner(cmd, stdin="", env=None):
        if "status" in cmd:
            is_b = bool(env and "claude-b" in str(env.get("CLAUDE_CONFIG_DIR", "")))
            ok = b_logged_in if is_b else True
            return (0, '{"loggedIn": true}') if ok else (0, '{"loggedIn": false}')
        return (0, "")
    return AvailabilityDetector(which=lambda c: f"/bin/{c}", runner=runner, environ={})


def test_account_b_absent_falls_back_to_primary():
    statuses = _two_account_detector(b_logged_in=False).detect_all(DEFAULT_CATALOG)
    by_id = {s.profile.id: s for s in statuses}
    assert by_id["claude-code-b"].available is False       # loggedIn:false caught
    assert by_id["claude-code"].available is True
    usable = select_models(statuses)
    assert usable["claude_b_fable"] == "claude-code"      # graceful fallback


def test_account_b_present_owns_its_model():
    statuses = _two_account_detector(b_logged_in=True).detect_all(DEFAULT_CATALOG)
    usable = select_models(statuses)
    assert usable["claude_b_fable"] == "claude-code-b"    # true 2-account team
    assert usable["claude_a_opus"] == "claude-code"     # A keeps the rest


def test_adapter_invokes_with_the_account_env(monkeypatch):
    from ammo.adapters import CommandAdapter, AdapterRequest

    seen = {}
    def runner(cmd, stdin="", env=None):
        seen["env"] = env
        return 0, '{"result": "OK", "usage": {"input_tokens": 1, "output_tokens": 1}}'
    monkeypatch.setenv("HOME", "/Users/tester")
    adapter = CommandAdapter("claude_b_fable", ["claude", "-p"], runner=runner,
                             env={"CLAUDE_CONFIG_DIR": "~/.claude-b"})
    adapter.execute(AdapterRequest(role="critic", model="claude_b_fable", task_input="x"))
    assert seen["env"]["CLAUDE_CONFIG_DIR"] == "/Users/tester/.claude-b"  # ~ expanded
    assert "PATH" in seen["env"]                            # os.environ preserved
