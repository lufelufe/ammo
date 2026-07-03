"""Provider profiles + availability status.

A provider is a *way to reach models* — a subscription CLI you're logged into, a
paid API key, or a local runtime. AMMO stores NO secrets: for API providers it
only checks whether the env var NAME is set (never its value); for CLI providers
it checks that the command exists and (optionally) that it is authenticated.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

# provider kinds
SUBSCRIPTION_CLI = "subscription_cli"
API = "api"
LOCAL = "local"


@dataclass
class ProviderProfile:
    id: str
    kind: str                                  # subscription_cli | api | local
    display_name: str
    command: Optional[str] = None              # CLI command name (cli/local)
    auth_check: Optional[List[str]] = None     # command probing authentication
    auth_expect: Optional[str] = None          # substring stdout must contain
                                               # (claude auth status exits 0 even
                                               # logged OUT — verified live)
    env: dict = field(default_factory=dict)    # per-provider env (paths only, no
                                               # secrets), e.g. CLAUDE_CONFIG_DIR
                                               # for a SECOND account slot
    list_command: Optional[List[str]] = None   # local: command that lists models
    env_var: Optional[str] = None              # api: env var NAME (presence only)
    invoke: Optional[List[str]] = None         # command to run a prompt ({model} placeholder)
    parser: Optional[str] = None               # usage-parser name (adapters/usage_parsers.py)
    models: List[str] = field(default_factory=list)
    model_args: dict = field(default_factory=dict)  # model_id -> extra CLI args
    cost: str = "included"                     # included (cli/local) | paid (api)
    # api providers: HTTP route (key read from env at CALL time, never stored)
    api_url: Optional[str] = None
    api_format: Optional[str] = None           # anthropic | openai
    api_models: dict = field(default_factory=dict)  # node id -> vendor model name


@dataclass
class ProviderStatus:
    profile: ProviderProfile
    available: bool
    detail: str
    models: List[str] = field(default_factory=list)

    def to_dict(self):
        return {
            "id": self.profile.id,
            "kind": self.profile.kind,
            "available": self.available,
            "detail": self.detail,
            "cost": self.profile.cost,
            "models": self.models,
        }


# Known providers. Included (subscription/local) are listed before paid API so
# that, for the same model, the no-extra-cost route is preferred.
DEFAULT_CATALOG: List[ProviderProfile] = [
    # Invocations & auth checks VERIFIED live on 2026-07-02
    # (claude 2.1.198, codex-cli 0.139.0):
    #   claude auth status  -> exit 0 + {"loggedIn": true} when authenticated
    #   echo <prompt> | claude -p               -> final answer on stdout (~5-20s)
    #   codex login status  -> exit 0 + "Logged in using ChatGPT"
    #   echo <prompt> | codex exec --skip-git-repo-check
    #       -> answer + "tokens used" on stdout; NOTE: a bare "-" arg would be
    #          read as the literal prompt, so the prompt goes via stdin only.
    # Structured-output invocations verified live 2026-07-02: claude JSON gives
    # result + usage + total_cost_usd; codex JSONL gives agent_message + usage.
    # Second Claude account slot (optional): CLAUDE_CONFIG_DIR separates auth
    # completely (verified live: a fresh dir reports loggedIn:false while the
    # default stays logged in). Log account B in with:
    #   CLAUDE_CONFIG_DIR=~/.claude-b claude  (then /login)
    # When B is authenticated, claude_b_critic runs on it (true 2-account
    # teams); when it is not, the entry is unavailable and claude_b falls back
    # to the primary account below. Listed FIRST so B wins for its model.
    ProviderProfile(
        "claude-code-b", SUBSCRIPTION_CLI, "Claude Code (account B)",
        command="claude", auth_check=["claude", "auth", "status"],
        auth_expect='"loggedIn": true',
        env={"CLAUDE_CONFIG_DIR": "~/.claude-b"},
        invoke=[
            "claude", "-p", "--output-format", "json",
            "--system-prompt",
            "You are one worker in an AMMO model team. You receive a role, a "
            "task, and prior members' outputs as context. Do your role's part "
            "directly and concisely. Do not use tools.",
            "--strict-mcp-config", "--disallowedTools", "*",
            "--no-session-persistence",
        ],
        parser="claude_json",
        models=["claude_b_critic"], cost="included",
        model_args={"claude_b_critic": ["--model", "claude-fable-5"]},
    ),
    # Lightweight worker mode MEASURED live 2026-07-02: replacing the full
    # Claude Code session surface (system prompt/MCP/tools/CLAUDE.md) with a
    # tiny worker prompt cut input tokens 22,803 -> 768 (~30x) and per-call
    # cost $0.134 -> $0.015 for the same one-line answer.
    ProviderProfile(
        "claude-code", SUBSCRIPTION_CLI, "Claude Code",
        command="claude", auth_check=["claude", "auth", "status"],
        auth_expect='"loggedIn": true',
        invoke=[
            "claude", "-p", "--output-format", "json",
            "--system-prompt",
            "You are one worker in an AMMO model team. You receive a role, a "
            "task, and prior members' outputs as context. Do your role's part "
            "directly and concisely. Do not use tools.",
            "--strict-mcp-config", "--disallowedTools", "*",
            "--no-session-persistence",
        ],
        parser="claude_json",
        # one subscription, several REAL models (--model): the pool diversity
        # the learning loop needs. haiku/sonnet live-verified 2026-07-02.
        models=["claude_a_planner", "claude_b_critic",
                "claude_haiku_fast", "claude_sonnet_worker"],
        model_args={
            "claude_b_critic": ["--model", "claude-fable-5"],
            "claude_haiku_fast": ["--model", "haiku"],
            "claude_sonnet_worker": ["--model", "sonnet"],
        },
        cost="included",
    ),
    ProviderProfile(
        "codex", SUBSCRIPTION_CLI, "Codex CLI",
        command="codex", auth_check=["codex", "login", "status"],
        invoke=["codex", "exec", "--skip-git-repo-check", "--json"],
        parser="codex_jsonl",
        models=["codex_builder"], cost="included",
    ),
    ProviderProfile(
        "ollama", LOCAL, "Ollama (local)",
        command="ollama", list_command=["ollama", "list"],
        invoke=["ollama", "run", "{model}"],
        cost="included",
    ),
    ProviderProfile(
        "anthropic-api", API, "Anthropic API",
        env_var="ANTHROPIC_API_KEY",
        models=["claude_a_planner", "claude_b_critic",
                "claude_haiku_fast", "claude_sonnet_worker"],
        cost="paid",
        api_url="https://api.anthropic.com/v1/messages",
        api_format="anthropic",
        api_models={
            "claude_a_planner": "claude-opus-4-8",
            "claude_b_critic": "claude-fable-5",
            "claude_haiku_fast": "claude-haiku-4-5",
            "claude_sonnet_worker": "claude-sonnet-5",
        },
    ),
    ProviderProfile(
        "openai-api", API, "OpenAI API",
        env_var="OPENAI_API_KEY", models=["codex_builder"], cost="paid",
        api_url="https://api.openai.com/v1/chat/completions",
        api_format="openai",
        # vendor model name is editable data — match it to your plan
        api_models={"codex_builder": "gpt-5"},
    ),
]
