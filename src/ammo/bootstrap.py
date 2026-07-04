"""The summon flow — `ammo start` and `ammo status`.

Summon word: **ammo**, identical in every environment. A host shim (AGENTS.md
instruction, slash command, alias) runs `python -m ammo start --host <id>`;
plain `ammo start` works in a terminal. Principles:

- Propose, don't interrogate: everything is detected first; the wizard only
  confirms (max 4 steps).
- Already configured → skip setup entirely and show the ready summary.
- Non-interactive summons configure safe defaults only; steps that GRANT
  PERMISSIONS (connect a workspace, bind models) are never auto-applied — the
  wizard prints how to do them explicitly instead.
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

from ammo.config import AmmoConfig, load_config, save_config

# host id -> provider id whose models anchor the primary seat
HOST_PROVIDER = {"claude-code": "claude-code", "codex": "codex"}


def detect_host(flag: Optional[str] = None, environ=None) -> str:
    """Host id: explicit shim flag wins; env fingerprints are a fallback."""
    if flag:
        return flag
    import os

    env = environ if environ is not None else os.environ
    if env.get("CLAUDECODE") or env.get("CLAUDE_CODE_ENTRYPOINT"):
        return "claude-code"
    if env.get("CODEX_SANDBOX") or env.get("CODEX_HOME"):
        return "codex"
    return "terminal"


def _detect_statuses(detector=None):
    from ammo.providers import DEFAULT_CATALOG, AvailabilityDetector

    detector = detector or AvailabilityDetector()
    return detector.detect_all(DEFAULT_CATALOG)


def build_status(root: Path) -> str:
    """One-screen ready summary (the repeat-summon view)."""
    from ammo.registry import SystemPackLoader

    config = load_config(root)
    lines = ["AMMO — Adaptive Multi-Model Orchestrator"]
    if config is None:
        lines.append("Not configured yet — run `ammo start` to set up.")
        return "\n".join(lines)

    primary = config.primary_model or "(none)"
    lines.append(
        f"host: {config.host}  primary: {primary}"
        + (f" via {config.primary_provider}" if config.primary_provider else "")
    )
    if config.models:
        lines.append(f"models: {', '.join(config.models)}")
    if config.roles:
        seats = " ".join(f"{slot}={model}" for slot, model in config.roles.items())
        lines.append(f"roles: {seats}")
    else:
        lines.append("roles: (not assigned yet — setup step below)")
    lines.append(f"objective: {config.default_objective}")

    systems = SystemPackLoader(root).available()
    lines.append(f"systems: {', '.join(systems) if systems else '(none connected)'}")

    db = root / "memory" / "ammo.sqlite"
    if db.is_file():
        from ammo.memory import MemoryStore

        with MemoryStore(db) as memory:
            stats = memory.stats()
        if stats["total_runs"]:
            lines.append(f"memory: {stats['total_runs']} run(s) recorded")
    lines.append('ready — `ammo enter` for a stay-inside session, '
                 'or `ammo run --real "..."` / `ammo status` anytime.')
    if not config.roles:
        lines.append("")
        lines.append(roles_setup_step(config.host))
    return "\n".join(lines)


def roles_setup_step(host: Optional[str]) -> str:
    """The 'assign your team roles' setup step, shown until roles exist.

    On an agent host (claude-code, codex, …) the host owns the UI, so this
    directs the host to run the interview as cards. In a bare terminal it points
    the user at the interactive `ammo roles set`.
    """
    if host and host != "terminal":
        return (
            "⚙ SETUP STEP — your team's roles aren't assigned yet.\n"
            f"  host ({host}): run the role interview now. Read the choices with\n"
            "    ammo roles plan --json\n"
            "  then ask the user seat by seat — orchestrator / critic / simple\n"
            "  worker / builder — and save the answers with\n"
            "    ammo roles set --orchestrator <id> --critic <id> "
            "--worker <id> --builder <id>"
        )
    return (
        "⚙ SETUP STEP — your team's roles aren't assigned yet.\n"
        "  run `./ammo roles set` for the interactive interview (Enter accepts the\n"
        "  proposed model per seat), or pass "
        "--orchestrator/--critic/--worker/--builder."
    )


def run_start(
    root: Path,
    host_flag: Optional[str] = None,
    *,
    reconfigure: bool = False,
    assume_yes: bool = False,
    detector=None,
    ask: Callable[[str], str] = input,
    interactive: Optional[bool] = None,
) -> int:
    """The summon wizard. Returns an exit code."""
    root = Path(root)
    if interactive is None:
        interactive = sys.stdin.isatty() and not assume_yes

    existing = load_config(root)
    if existing is not None and not reconfigure:
        print(build_status(root))
        return 0

    host = detect_host(host_flag)
    print("AMMO — first summon setup (4 steps; re-run anytime with --reconfigure)")

    # [1/4] host -> primary model
    statuses = _detect_statuses(detector)
    from ammo.providers import select_models

    usable = select_models(statuses)  # model -> provider (no-extra-cost first)
    host_provider = HOST_PROVIDER.get(host)
    host_models = [m for m, p in usable.items() if p == host_provider]
    primary_model = host_models[0] if host_models else (next(iter(usable), None))
    primary_provider = usable.get(primary_model) if primary_model else None

    print(f"[1/4] Host: {host}"
          + (f" — proposing {primary_model} (via {primary_provider}) as primary"
             if primary_model else " — no usable model detected for this host"))
    if interactive and primary_model:
        answer = ask("      Use it as the primary model? [Y/n]: ").strip().lower()
        if answer in {"n", "no"}:
            custom = ask("      Primary model id (blank = none): ").strip()
            primary_model = custom or None
            primary_provider = usable.get(primary_model) if primary_model else None

    # [2/4] team model set
    model_ids = sorted(usable)
    print(f"[2/4] Usable models: {', '.join(model_ids) if model_ids else '(none)'}")
    chosen = model_ids
    if interactive and model_ids:
        answer = ask("      Use all as the preferred set? [Y/n or comma-separated ids]: ").strip()
        if answer.lower() in {"n", "no"}:
            chosen = [primary_model] if primary_model else []
        elif answer and answer.lower() not in {"y", "yes"}:
            chosen = [m.strip() for m in answer.split(",") if m.strip()]

    # [3/4] workspace — grants permissions, so never auto-applied
    print("[3/4] Workspace: connecting a directory grants filesystem access, so it")
    print("      stays explicit — use `ammo connect <path>` (asks read-only vs")
    print("      read-write) and `ammo bind <system>` for a per-system team.")

    # [4/4] objective
    objective = "balanced"
    if interactive:
        answer = ask("[4/4] Default objective [balanced/performance/cost/speed] (Enter=balanced): ").strip().lower()
        if answer in {"performance", "cost", "speed"}:
            objective = answer
    else:
        print("[4/4] Default objective: balanced (change later with `ammo start --reconfigure`)")

    config = AmmoConfig(
        host=host,
        primary_provider=primary_provider,
        primary_model=primary_model,
        models=chosen,
        default_objective=objective,
        configured_at=datetime.now(timezone.utc).isoformat(),
    )
    path = save_config(root, config)
    print(f"✓ Saved {path.name}")
    print(build_status(root))
    return 0
