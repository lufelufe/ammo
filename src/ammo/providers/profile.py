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
    auth_check: Optional[List[str]] = None     # command whose exit 0 == authenticated
    list_command: Optional[List[str]] = None   # local: command that lists models
    env_var: Optional[str] = None              # api: env var NAME (presence only)
    invoke: Optional[List[str]] = None         # command to run a prompt ({model} placeholder)
    parser: Optional[str] = None               # usage-parser name (adapters/usage_parsers.py)
    models: List[str] = field(default_factory=list)
    cost: str = "included"                     # included (cli/local) | paid (api)


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
    ProviderProfile(
        "claude-code", SUBSCRIPTION_CLI, "Claude Code",
        command="claude", auth_check=["claude", "auth", "status"],
        invoke=["claude", "-p", "--output-format", "json"],
        parser="claude_json",
        models=["claude_a_planner", "claude_b_critic"], cost="included",
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
        models=["claude_a_planner", "claude_b_critic"], cost="paid",
    ),
    ProviderProfile(
        "openai-api", API, "OpenAI API",
        env_var="OPENAI_API_KEY", models=["codex_builder"], cost="paid",
    ),
]
