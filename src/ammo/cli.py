"""AMMO command-line interface (Milestone 0 placeholder).

This CLI deliberately does **not** perform any orchestration. It exists so that
``python -m ammo --help`` works and to give later milestones a stable entry
point to build on. No model calls, no team formation, no secrets.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Sequence

from ammo import __version__
from ammo.binding import (
    BindingStore,
    available_choices,
    build_binding,
    existing_or_best,
)
from ammo.connect import ConnectError, SystemConnector
from ammo.doctor import run_doctor
from ammo.kernel.evaluation import EvaluationEngine
from ammo.adapters import MockAdapter, RealAdapterFactory
from ammo.kernel.capability_graph import CapabilityGraph, score_models, task_needs
from ammo.kernel.confidence import ConfidenceEngine
from ammo.kernel.executor import Runner, RunStore
from ammo.kernel.task_understanding import TaskAnalyzer
from ammo.kernel.team_formation import TeamFormer
from ammo.memory import MemoryAdvisor, MemoryStore, team_signature
from ammo.paths import find_ammo_root
from ammo.roles import RoleWorkspace
from ammo.registry import RegistryError, SystemPackLoader, enabled_systems

TAGLINE = "AMMO is not a router. AMMO is the adaptive orchestration kernel of a Personal AI OS."


def build_parser() -> argparse.ArgumentParser:
    """Build the top-level argument parser."""
    parser = argparse.ArgumentParser(
        prog="ammo",
        description=(
            "AMMO — the Adaptive Multi-Model Orchestrator. "
            "Kernel of a Personal AI OS. (Milestone 0: bootstrap; no "
            "orchestration logic yet.)"
        ),
        epilog=TAGLINE,
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"ammo {__version__}",
    )

    subparsers = parser.add_subparsers(dest="command", metavar="<command>")

    version_parser = subparsers.add_parser(
        "version",
        help="Print the AMMO kernel version.",
    )
    version_parser.set_defaults(func=_cmd_version)

    start_parser = subparsers.add_parser(
        "start",
        help="Summon AMMO: first-run setup wizard, or the ready summary if configured.",
    )
    start_parser.add_argument("--host", help="Summoning environment id (e.g. claude-code, codex).")
    start_parser.add_argument("--yes", action="store_true",
                              help="Non-interactive: accept safe defaults.")
    start_parser.add_argument("--reconfigure", action="store_true",
                              help="Redo setup even if already configured.")
    start_parser.set_defaults(func=_cmd_start)

    status_parser = subparsers.add_parser(
        "status", help="One-screen summary of host, models, systems, and memory.",
    )
    status_parser.set_defaults(func=_cmd_status)

    doctor_parser = subparsers.add_parser(
        "doctor",
        help="Check that the AMMO root structure is healthy.",
    )
    doctor_parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Show details for passing checks too.",
    )
    doctor_parser.set_defaults(func=_cmd_doctor)

    list_parser = subparsers.add_parser(
        "list-systems",
        help="List enabled system packs from registry/systems.yaml.",
    )
    list_parser.set_defaults(func=_cmd_list_systems)

    inspect_parser = subparsers.add_parser(
        "inspect-system",
        help="Print a structured summary of one system pack.",
    )
    inspect_parser.add_argument(
        "system",
        metavar="SYSTEM",
        help="System pack id (e.g. personal, research, coding, ops).",
    )
    inspect_parser.set_defaults(func=_cmd_inspect_system)

    analyze_parser = subparsers.add_parser(
        "analyze",
        help="Analyze a request into a TaskVector (rule-based, no model call).",
    )
    analyze_parser.add_argument(
        "text",
        metavar="TEXT",
        help="The request to analyze, e.g. \"fix the bug in this Python repo and add tests\".",
    )
    analyze_parser.set_defaults(func=_cmd_analyze)

    list_models_parser = subparsers.add_parser(
        "list-models",
        help="List model nodes in the capability graph (registry/models.yaml).",
    )
    list_models_parser.set_defaults(func=_cmd_list_models)

    score_parser = subparsers.add_parser(
        "score-models",
        help="Score capability-graph models against a request (no model call).",
    )
    score_parser.add_argument("text", metavar="TEXT", help="The request to score models for.")
    score_parser.set_defaults(func=_cmd_score_models)

    plan_parser = subparsers.add_parser(
        "plan-team",
        help="Form a team (ExecutionPlan) for a request (no execution).",
    )
    plan_parser.add_argument("text", metavar="TEXT", help="The request to plan a team for.")
    plan_parser.add_argument(
        "--no-memory", action="store_true",
        help="Ignore run memory; use static capability scoring only.",
    )
    plan_parser.add_argument(
        "--explore", type=float, nargs="?", const=1.0, default=0.0,
        help="Exploration nudge for under-tried models (default off; bare flag = 1.0).",
    )
    plan_parser.add_argument(
        "--optimize", choices=["balanced", "performance", "cost", "speed"],
        default=None,
        help="Objective for team selection (default: configured value or balanced).",
    )
    plan_parser.set_defaults(func=_cmd_plan_team)

    run_parser = subparsers.add_parser(
        "run",
        help="Analyze, form a team, and execute a request (mock only for now).",
    )
    run_parser.add_argument(
        "--mock",
        action="store_true",
        help="Use deterministic mock adapters (no real model call).",
    )
    run_parser.add_argument(
        "--real",
        action="store_true",
        help="Call authenticated CLIs for available models (falls back to mock otherwise).",
    )
    run_parser.add_argument(
        "--allow-paid",
        action="store_true",
        help="With --real, allow paid API routes when resolving models.",
    )
    run_parser.add_argument(
        "--execute-tools",
        action="store_true",
        help="Execute permitted side-effecting tools in an isolated per-run sandbox.",
    )
    run_parser.add_argument(
        "--show-confidence",
        action="store_true",
        help="Print the evidence-based confidence card after the run.",
    )
    run_parser.add_argument(
        "--no-memory", action="store_true",
        help="Ignore run memory when forming the team.",
    )
    run_parser.add_argument(
        "--explore", type=float, nargs="?", const=1.0, default=0.0,
        help="Exploration nudge for under-tried models (default off; bare flag = 1.0).",
    )
    run_parser.add_argument(
        "--optimize", choices=["balanced", "performance", "cost", "speed"],
        default=None,
        help="Objective for team selection (default: configured value or balanced).",
    )
    run_parser.add_argument("text", metavar="TEXT", help="The request to run.")
    run_parser.set_defaults(func=_cmd_run)

    show_run_parser = subparsers.add_parser(
        "show-run",
        help="Show a stored run summary by id (from runtime/runs/).",
    )
    show_run_parser.add_argument("run_id", metavar="RUN_ID", help="The run id to show.")
    show_run_parser.set_defaults(func=_cmd_show_run)

    memory_parser = subparsers.add_parser("memory", help="Inspect AMMO's run memory.")
    memory_parser.set_defaults(func=_cmd_memory_help)
    memory_sub = memory_parser.add_subparsers(dest="memory_command", metavar="<command>")
    memory_stats = memory_sub.add_parser("stats", help="Show memory aggregates.")
    memory_stats.set_defaults(func=_cmd_memory_stats)
    memory_runs = memory_sub.add_parser("runs", help="List recent recorded runs.")
    memory_runs.add_argument("--limit", type=int, default=20, help="Max runs to show.")
    memory_runs.set_defaults(func=_cmd_memory_runs)

    new_system_parser = subparsers.add_parser(
        "new-system", help="Scaffold a new in-tree system pack.",
    )
    new_system_parser.add_argument("system_id", metavar="ID", help="New system pack id.")
    new_system_parser.add_argument("--description", help="One-line description.")
    new_system_parser.set_defaults(func=_cmd_new_system)

    connect_parser = subparsers.add_parser(
        "connect", help="Attach an external directory as a system pack (by reference).",
    )
    connect_parser.add_argument("path", metavar="PATH", help="Directory to connect.")
    connect_parser.add_argument("--id", dest="system_id", help="Pack id (default: folder name).")
    connect_parser.add_argument(
        "--read-only", action="store_true", help="Grant read-only access (skips the prompt).",
    )
    connect_parser.add_argument(
        "--writable", action="store_true", help="Grant read-write access (skips the prompt).",
    )
    connect_parser.add_argument(
        "--tools", help="Comma-separated tool ids to allow (must exist in registry/tools.yaml).",
    )
    connect_parser.add_argument("--description", help="One-line description.")
    connect_parser.set_defaults(func=_cmd_connect)

    disconnect_parser = subparsers.add_parser(
        "disconnect", help="Remove a system pack descriptor (never deletes mounted data).",
    )
    disconnect_parser.add_argument("system_id", metavar="ID", help="System pack id to remove.")
    disconnect_parser.set_defaults(func=_cmd_disconnect)

    adopt_parser = subparsers.add_parser(
        "adopt",
        help="Idempotently bring systems/<id> up to contract, preserving existing files.",
    )
    adopt_parser.add_argument("system_id", metavar="ID", help="System pack id (folder under systems/).")
    adopt_parser.add_argument("--description", help="One-line description (only used for new files).")
    adopt_parser.set_defaults(func=_cmd_adopt)

    eval_parser = subparsers.add_parser(
        "eval-system", help="Evaluate one system's health (works / improvements / problems).",
    )
    eval_parser.add_argument("system_id", metavar="ID", help="System pack id to evaluate.")
    eval_parser.set_defaults(func=_cmd_eval_system)

    eval_all_parser = subparsers.add_parser(
        "eval-systems", help="Evaluate every discovered system.",
    )
    eval_all_parser.set_defaults(func=_cmd_eval_systems)

    providers_parser = subparsers.add_parser(
        "providers",
        help="Detect available model providers (subscription CLIs, API keys, local).",
    )
    providers_parser.add_argument(
        "--allow-paid", action="store_true",
        help="Include paid API routes when listing usable models.",
    )
    providers_parser.set_defaults(func=_cmd_providers)

    bind_parser = subparsers.add_parser(
        "bind",
        help="Select and bind models to a system (reuses the best-known combo if present).",
    )
    bind_parser.add_argument("system_id", metavar="SYSTEM", help="System pack id to bind.")
    bind_parser.add_argument("--models", help="Comma-separated model ids (skips prompts).")
    bind_parser.add_argument("--reuse", action="store_true", help="Reuse the proposed combination.")
    bind_parser.add_argument("--allow-paid", action="store_true", help="Allow paid API routes.")
    bind_parser.set_defaults(func=_cmd_bind)

    role_log_parser = subparsers.add_parser(
        "role-log", help="Show a role's working-directory journal for a system.",
    )
    role_log_parser.add_argument("system_id", metavar="SYSTEM", help="System pack id.")
    role_log_parser.add_argument("role", metavar="ROLE", help="Role name (e.g. builder).")
    role_log_parser.add_argument("--limit", type=int, default=10, help="Max entries to show.")
    role_log_parser.set_defaults(func=_cmd_role_log)

    eval_suite_parser = subparsers.add_parser(
        "eval", help="Run the eval suite and score AMMO's decisions (mock only).",
    )
    eval_suite_parser.add_argument(
        "--mock", action="store_true", help="Run with mock adapters (required; no real models).",
    )
    eval_suite_parser.set_defaults(func=_cmd_eval)

    pricing_parser = subparsers.add_parser(
        "pricing", help="Show or update the per-model pricing book (no secrets).",
    )
    pricing_parser.set_defaults(func=_cmd_pricing_show)
    pricing_sub = pricing_parser.add_subparsers(dest="pricing_command", metavar="<command>")
    pricing_show = pricing_sub.add_parser("show", help="List model prices.")
    pricing_show.set_defaults(func=_cmd_pricing_show)
    pricing_set = pricing_sub.add_parser("set", help="Set a model's per-MTok prices.")
    pricing_set.add_argument("model_id", metavar="MODEL")
    pricing_set.add_argument("price_in", type=float, metavar="IN_PER_MTOK")
    pricing_set.add_argument("price_out", type=float, metavar="OUT_PER_MTOK")
    pricing_set.add_argument("--billing", choices=["api", "subscription", "local"])
    pricing_set.set_defaults(func=_cmd_pricing_set)

    promote_parser = subparsers.add_parser(
        "promote",
        help="Apply a run's sandboxed writes to the real target (diff first, then --apply).",
    )
    promote_parser.add_argument("run_id", metavar="RUN_ID")
    promote_parser.add_argument("--to", help="Target root (default: the system's source_path).")
    promote_parser.add_argument("--apply", action="store_true",
                                help="Copy the files (default: dry-run diff).")
    promote_parser.set_defaults(func=_cmd_promote)

    dream_parser = subparsers.add_parser(
        "dream",
        help="Consolidate memory: rebuild aggregates, drop orphans, prune, distill journals.",
    )
    dream_parser.add_argument("--apply", action="store_true",
                              help="Perform the consolidation (default: dry-run report).")
    dream_parser.add_argument("--window", type=int, default=50,
                              help="Recent runs to keep/rebuild from (default 50).")
    dream_parser.add_argument("--journal-keep", type=int, default=20,
                              help="Journal entries to keep per role (default 20).")
    dream_parser.set_defaults(func=_cmd_dream)

    efficiency_parser = subparsers.add_parser(
        "efficiency", help="Quality-per-cost report from recorded runs.",
    )
    efficiency_parser.add_argument("--system", help="Limit to one system/tag.")
    efficiency_parser.set_defaults(func=_cmd_efficiency)

    return parser


def _cmd_eval(args: argparse.Namespace) -> int:
    if not args.mock:
        print("Only --mock eval is available in this milestone (no real models).")
        return 2

    from ammo.evalsuite import EvalSuite, load_cases

    root = find_ammo_root()
    cases = load_cases(root / "evals")
    if not cases:
        print(f"No eval cases found under {root / 'evals'}.")
        return 1

    report = EvalSuite(root=root).run(cases)

    print(f"AMMO eval (mock) — {report.cases_passed}/{len(report.results)} cases fully correct")
    for metric, tally in report.metric_totals().items():
        print(f"  {metric}: {tally['passed']}/{tally['total']}")
    for result in report.results:
        if not result.passed:
            failed = [m for m, ok in result.metrics.items() if not ok]
            print(f"  ! {result.id} failed: {', '.join(failed)}  observed={result.observed}")

    now = datetime.now(timezone.utc)
    reports_dir = root / "runtime" / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    path = reports_dir / f"eval-{now.strftime('%Y%m%dT%H%M%SZ')}.json"
    path.write_text(
        json.dumps({"created_at": now.isoformat(), **report.to_dict()}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"report: {path}")
    return 0 if report.all_passed else 1


def _cmd_version(_args: argparse.Namespace) -> int:
    print(f"ammo {__version__}")
    return 0


def _cmd_start(args: argparse.Namespace) -> int:
    from ammo.bootstrap import run_start

    return run_start(
        find_ammo_root(), args.host,
        reconfigure=args.reconfigure, assume_yes=args.yes,
    )


def _cmd_status(_args: argparse.Namespace) -> int:
    from ammo.bootstrap import build_status

    print(build_status(find_ammo_root()))
    return 0


def _load_pack_for_task(root, task):
    """The candidate system's pack (specs: preferences/verification/limits/context)."""
    system_id = task.candidate_systems[0] if task.candidate_systems else None
    if not system_id:
        return None
    try:
        return SystemPackLoader(root).load(system_id)
    except RegistryError:
        return None


def _role_memory(root, system, roles):
    """Distilled per-role memory (insights.md + last.md) for read-back injection."""
    if not system:
        return {}
    workspace = RoleWorkspace(root)
    out = {}
    for role in roles:
        role_dir = workspace.path(system, role)
        parts = []
        for name in ("insights.md", "last.md"):
            f = role_dir / name
            if f.is_file():
                parts.append(f.read_text(encoding="utf-8")[-800:])
        if parts:
            out[role] = "\n".join(parts)
    return out


def _load_primary(root):
    """The summoning host's model from ammo.config.yaml (None if unset)."""
    from ammo.config import load_config

    config = load_config(root)
    return config.primary_model if config else None


def _resolve_objective(root, args) -> str:
    """CLI flag wins; else the configured default; else balanced."""
    flag = getattr(args, "optimize", None)
    if flag:
        return flag
    from ammo.config import load_config

    config = load_config(root)
    return config.default_objective if config else "balanced"


def _cmd_doctor(args: argparse.Namespace) -> int:
    report = run_doctor(find_ammo_root())
    print(f"AMMO doctor — root: {report.root}")
    for check in report.checks:
        mark = "✓" if check.ok else "✗"
        line = f"  {mark} {check.name}"
        if check.detail and (not check.ok or args.verbose):
            line += f"  ({check.detail})"
        print(line)

    passed = sum(1 for c in report.checks if c.ok)
    print(f"\n{passed}/{len(report.checks)} checks passed.")
    if report.notices:
        print("\nNotices:")
        for notice in report.notices:
            print(f"  ! {notice}")
    if report.ok:
        print("AMMO structure looks healthy.")
        return 0
    print("AMMO structure has problems (see the marked lines above).")
    return 1


def _print_system_line(loader, system_id, status, description):
    badge = f" [{status}]" if status else ""
    suffix = f"  {description}" if description else ""
    mount = ""
    try:
        pack = loader.load(system_id)
        if pack.source_path:
            mount = f"  (mounted: {pack.source_path})"
    except RegistryError:
        pass
    print(f"  - {system_id}{badge}{suffix}{mount}")


def _cmd_list_systems(_args: argparse.Namespace) -> int:
    root = find_ammo_root()
    loader = SystemPackLoader(root)
    declared = enabled_systems(root)  # from registry/systems.yaml
    declared_ids = {s.get("id") for s in declared}

    print("Enabled systems:")
    for system in declared:
        _print_system_line(loader, system.get("id", "?"), system.get("status", ""),
                            system.get("description", ""))
    # discovered-on-disk packs not declared in systems.yaml (connected / scaffolded)
    for system_id in loader.available():
        if system_id in declared_ids:
            continue
        try:
            pack = loader.load(system_id)
            _print_system_line(loader, system_id, pack.status, pack.description)
        except RegistryError as exc:
            print(f"  - {system_id}  [invalid: {exc}]")
    return 0


def _cmd_new_system(args: argparse.Namespace) -> int:
    connector = SystemConnector(find_ammo_root())
    try:
        path = connector.new_system(args.system_id, description=args.description)
    except ConnectError as exc:
        print(f"Error: {exc}")
        return 1
    print(f"Created system pack: {path}")
    return 0


def _ask_access() -> Optional[bool]:
    """Ask read-only vs read-write. Returns True/False, or None if not a TTY."""
    if not sys.stdin.isatty():
        return None
    while True:
        answer = input(
            "Grant access to this directory — [r]ead-only or read-[w]rite? [r/w]: "
        ).strip().lower()
        if answer in {"r", "read", "ro", "read-only", "readonly"}:
            return False
        if answer in {"w", "write", "rw", "read-write", "readwrite"}:
            return True
        print("Please answer 'r' (read-only) or 'w' (read-write).")


def _cmd_connect(args: argparse.Namespace) -> int:
    if args.read_only and args.writable:
        print("Error: choose either --read-only or --writable, not both.")
        return 2
    if args.read_only:
        writable = False
    elif args.writable:
        writable = True
    else:
        writable = _ask_access()
        if writable is None:
            print("Error: specify --read-only or --writable (no interactive terminal to ask).")
            return 2

    connector = SystemConnector(find_ammo_root())
    tools = [t.strip() for t in args.tools.split(",")] if args.tools else None
    try:
        path = connector.connect(
            args.path,
            system_id=args.system_id,
            writable=writable,
            tools=tools,
            description=args.description,
        )
    except ConnectError as exc:
        print(f"Error: {exc}")
        return 1
    access = "read-write" if writable else "read-only"
    print(f"Connected system pack: {path}")
    print(f"access: {access}  (the source directory was referenced in place, not moved)")
    return 0


def _cmd_disconnect(args: argparse.Namespace) -> int:
    connector = SystemConnector(find_ammo_root())
    try:
        path = connector.disconnect(args.system_id)
    except ConnectError as exc:
        print(f"Error: {exc}")
        return 1
    print(f"Disconnected system pack: {path}")
    print("(the mounted source directory, if any, was not touched)")
    return 0


def _cmd_pricing_show(_args: argparse.Namespace) -> int:
    from ammo.economics import PricingBook

    book = PricingBook.load(find_ammo_root())
    if not book.prices:
        print("No pricing book found (registry/pricing.yaml).")
        return 0
    print(f"Pricing ({book.currency}/MTok, as of {book.as_of or 'unknown'}):")
    for price in sorted(book.prices.values(), key=lambda p: p.id):
        print(f"  - {price.id:22} in ${price.price_per_mtok_in:<7g} "
              f"out ${price.price_per_mtok_out:<7g} [{price.billing}] ({price.source})")
    return 0


def _cmd_pricing_set(args: argparse.Namespace) -> int:
    from ammo.economics import PricingBook

    book = PricingBook.load(find_ammo_root())
    price = book.set_price(args.model_id, args.price_in, args.price_out,
                           billing=args.billing)
    book.save()
    print(f"Updated {price.id}: in ${price.price_per_mtok_in}/MTok, "
          f"out ${price.price_per_mtok_out}/MTok [{price.billing}]")
    return 0


def _cmd_promote(args: argparse.Namespace) -> int:
    from ammo.tools.promote import PromoteError, plan_promotion

    try:
        report = plan_promotion(find_ammo_root(), args.run_id, to=args.to,
                                apply=args.apply)
    except PromoteError as exc:
        print(f"promote: {exc}", file=sys.stderr)
        return 1
    print(report.to_text())
    return 0


def _cmd_dream(args: argparse.Namespace) -> int:
    from ammo.dream import DreamEngine

    engine = DreamEngine(find_ammo_root(), window=args.window,
                         journal_keep=args.journal_keep)
    report = engine.apply() if args.apply else engine.plan()
    print(report.to_text())
    return 0


def _cmd_efficiency(args: argparse.Namespace) -> int:
    root = find_ammo_root()
    if not (root / "memory" / "ammo.sqlite").is_file():
        print("No run memory yet — run some tasks first (`ammo run --mock ...`).")
        return 0

    with MemoryStore.open(root) as memory:
        models = memory.all_model_performance()
        teams = memory.all_team_synergy()

    if args.system:
        models = [m for m in models if m["task_tag"] == args.system]
        teams = [t for t in teams if t["task_tag"] == args.system]
    if not models:
        print("No recorded performance for that scope.")
        return 0

    def model_efficiency(m):
        cost = m.get("average_cost") or 0.0
        conf = m.get("average_confidence") or 0.0
        return conf / cost if cost > 0 else float("inf") if conf > 0 else 0.0

    print("Model efficiency (quality per $; local/subscription-covered = inf):")
    for m in sorted(models, key=lambda m: (m["task_tag"], -model_efficiency(m))):
        eff = model_efficiency(m)
        eff_str = "inf" if eff == float("inf") else f"{eff:.0f}"
        print(f"  [{m['task_tag']}] {m['model_id']:22} conf {m['average_confidence']:<5} "
              f"tokens {m.get('average_tokens') or 0:<7} cost ${m.get('average_cost') or 0:.4f} "
              f" eff {eff_str}")

    if teams:
        print("Team combinations:")
        for t in sorted(teams, key=lambda t: (t["task_tag"], -(t["average_confidence"] or 0))):
            print(f"  [{t['task_tag']}] {t['team_signature']}")
            print(f"      attempts {t['attempts']}  success {t['successes']}  "
                  f"conf {t['average_confidence']}  cost ${t.get('average_cost') or 0:.4f}")
    return 0


def _cmd_role_log(args: argparse.Namespace) -> int:
    workspace = RoleWorkspace(find_ammo_root())
    entries = workspace.journal(args.system_id, args.role)
    if not entries:
        print(f"No journal for role '{args.role}' in '{args.system_id}'.")
        return 0
    print(f"Role '{args.role}' in '{args.system_id}' — {len(entries)} entr(ies):")
    for entry in entries[-args.limit:]:
        output = (entry.get("output") or "").replace("\n", " ")
        print(f"  - {entry.get('timestamp', '')} [{entry.get('model', '?')}] {output[:80]}")
    return 0


def _cmd_providers(args: argparse.Namespace) -> int:
    from ammo.providers import DEFAULT_CATALOG, AvailabilityDetector, select_models

    statuses = AvailabilityDetector().detect_all(DEFAULT_CATALOG)
    print("Providers:")
    for status in statuses:
        mark = "✓" if status.available else "·"
        cost = f"  ${status.profile.cost}" if status.profile.cost == "paid" else ""
        print(f"  {mark} {status.profile.id} [{status.profile.kind}]  {status.detail}{cost}")

    usable = select_models(statuses, allow_paid=args.allow_paid)
    if usable:
        print("\nUsable models (no extra cost preferred):")
        for model_id, provider_id in sorted(usable.items()):
            print(f"  - {model_id}  via {provider_id}")
    else:
        print("\nNo real providers available — connect a subscription CLI, set an "
              "API key, or install a local runtime (or use `run --mock`).")
    return 0


def _confirm(prompt: str) -> bool:
    while True:
        answer = input(f"{prompt} [y/n]: ").strip().lower()
        if answer in {"y", "yes"}:
            return True
        if answer in {"n", "no"}:
            return False


def _prompt_models(choices) -> Optional[list]:
    if not choices:
        print("No models auto-detected.")
    else:
        print("Available models:")
        for i, c in enumerate(choices, 1):
            print(f"  {i}) {c['model']}  via {c['provider']} [{c['kind']}]")
    print("  0) enter a custom model id")
    raw = input("Select models by number (comma-separated), or type ids: ").strip()
    if not raw:
        return None
    picked = []
    for token in raw.split(","):
        token = token.strip()
        if token == "0":
            custom = input("Custom model id: ").strip()
            if custom:
                picked.append(custom)
        elif token.isdigit() and 1 <= int(token) <= len(choices):
            picked.append(choices[int(token) - 1]["model"])
        elif token:
            picked.append(token)  # typed a model id directly
    return picked


def _resolve_choices(model_ids, choices):
    by_model = {c["model"]: c for c in choices}
    resolved = []
    for model_id in model_ids:
        c = by_model.get(model_id)
        resolved.append({"model": model_id, "provider": c["provider"] if c else "custom"})
    return resolved


def _verify_binding(binding, allow_paid: bool) -> None:
    from ammo.providers import DEFAULT_CATALOG, AvailabilityDetector, select_models

    usable = select_models(AvailabilityDetector().detect_all(DEFAULT_CATALOG), allow_paid=allow_paid)
    print("Verification:")
    for entry in binding.models:
        model_id = entry.get("id")
        ok = model_id in usable
        mark = "✓" if ok else "·"
        detail = f"via {usable[model_id]}" if ok else "not currently available (custom/offline)"
        print(f"  {mark} {model_id}  {detail}")


def _print_binding(binding) -> None:
    print(f"models: {', '.join(m['id'] for m in binding.models) or '(none)'}")
    if binding.team:
        pairs = [f"{t['role']}:{t['model']}" for t in binding.team]
        print(f"team: {', '.join(pairs)}")


def _cmd_bind(args: argparse.Namespace) -> int:
    root = find_ammo_root()
    system = args.system_id
    if not (root / "systems" / system / ".ammo").is_dir():
        print(f"Error: no system pack '{system}'. Run `ammo adopt {system}` or `ammo connect` first.")
        return 1

    store = BindingStore(root)
    proposal = existing_or_best(root, system)

    # reuse path (default when a proposal exists and no fresh --models requested)
    if proposal and not args.models:
        reuse = True
        if sys.stdin.isatty() and not args.reuse:
            reuse = _confirm(f"Reuse the {proposal['source']} combination for '{system}'?")
        if reuse:
            binding = proposal["binding"]
            binding.system = system
            path = store.save(binding)
            print(f"Bound '{system}' (reused {proposal['source']}): {path}")
            _print_binding(binding)
            _verify_binding(binding, args.allow_paid)
            return 0

    # fresh selection (1 -> 1a/1b -> 2 -> 3)
    from ammo.providers import DEFAULT_CATALOG, AvailabilityDetector

    statuses = AvailabilityDetector().detect_all(DEFAULT_CATALOG)
    choices = available_choices(statuses, allow_paid=args.allow_paid)
    if args.models:
        picked = [m.strip() for m in args.models.split(",") if m.strip()]
    elif sys.stdin.isatty():
        picked = _prompt_models(choices)
        if not picked:
            print("Cancelled — no models selected.")
            return 1
    else:
        print("Error: specify --models a,b,... or --reuse (no interactive terminal).")
        return 2

    binding = build_binding(system, _resolve_choices(picked, choices), allow_paid=args.allow_paid)
    path = store.save(binding)
    print(f"Bound '{system}': {path}")
    _print_binding(binding)
    _verify_binding(binding, args.allow_paid)
    return 0


def _cmd_adopt(args: argparse.Namespace) -> int:
    connector = SystemConnector(find_ammo_root())
    try:
        result = connector.adopt(args.system_id, description=args.description)
    except ConnectError as exc:
        print(f"Error: {exc}")
        return 1
    print(f"Adopted system pack: {result['path']}")
    print(f"added: {', '.join(result['added']) or '(none)'}")
    print(f"preserved: {', '.join(result['preserved']) or '(none)'}")
    return 0


def _cmd_eval_system(args: argparse.Namespace) -> int:
    report = EvaluationEngine().evaluate(find_ammo_root(), args.system_id)
    print(report.to_card())
    return 1 if report.health == "at_risk" else 0


def _cmd_eval_systems(_args: argparse.Namespace) -> int:
    root = find_ammo_root()
    engine = EvaluationEngine()
    systems = SystemPackLoader(root).available()
    if not systems:
        print("No systems to evaluate.")
        return 0
    worst_ok = True
    for system_id in systems:
        report = engine.evaluate(root, system_id)
        print(f"- {system_id}: {report.health}")
        if report.health == "at_risk":
            worst_ok = False
    return 0 if worst_ok else 1


def _cmd_inspect_system(args: argparse.Namespace) -> int:
    loader = SystemPackLoader(find_ammo_root())
    try:
        pack = loader.load(args.system)
    except RegistryError as exc:
        print(f"Error: {exc}")
        return 1

    for line in pack.summary_lines():
        print(line)
    return 0


def _cmd_analyze(args: argparse.Namespace) -> int:
    vector = TaskAnalyzer().analyze(args.text)
    print(json.dumps(vector.to_dict(), ensure_ascii=False, indent=2))
    return 0


def _cmd_list_models(_args: argparse.Namespace) -> int:
    graph = CapabilityGraph.from_registry(find_ammo_root())
    if not graph.nodes:
        print("No models found in registry/models.yaml.")
        return 0
    print("Models (capability graph):")
    for node in graph.nodes:
        state = "enabled" if node.enabled else "disabled"
        print(
            f"  - {node.id}  [{node.provider}]  "
            f"roles={','.join(node.roles) or '-'}  "
            f"caps={','.join(node.capabilities) or '-'}  "
            f"ctx={node.context_window}  cost={node.cost_class}  "
            f"lat={node.latency_class}  {node.warm_status}  ({state})"
        )
    return 0


def _cmd_score_models(args: argparse.Namespace) -> int:
    graph = CapabilityGraph.from_registry(find_ammo_root())
    task = TaskAnalyzer().analyze(args.text)
    ranked = score_models(task, graph)

    primary, secondary, caps = task_needs(task)
    print(f"Task: {task.domain} / {task.intent}  (risk {task.risk}, ctx {task.context_size})")
    print(f"  needs roles: {', '.join(sorted(primary | secondary)) or '(none)'}")
    print(f"  needs capabilities: {', '.join(sorted(caps)) or '(none)'}")
    print("Ranked models:")
    for rank, scored in enumerate(ranked, start=1):
        reasons = ", ".join(scored.reasons) or "-"
        print(f"  {rank:2}. {scored.model_id:20} score {scored.score:>3}  [{reasons}]")
    return 0


def _load_memory_advisor(root, args) -> Optional[MemoryAdvisor]:
    explore = float(getattr(args, "explore", 0.0) or 0.0)
    if getattr(args, "no_memory", False):
        return None
    # cold start: no memory db yet. Still allow exploration to try untried models.
    if not (Path(root) / "memory" / "ammo.sqlite").is_file():
        return MemoryAdvisor({}, {}, explore=explore) if explore > 0 else None
    with MemoryStore.open(root) as memory:
        return MemoryAdvisor.from_store(memory, explore=explore)


def _load_binding(root, task):
    if not task.candidate_systems:
        return None
    try:
        return BindingStore(root).load(task.candidate_systems[0])
    except Exception:
        return None


def _cmd_plan_team(args: argparse.Namespace) -> int:
    root = find_ammo_root()
    graph = CapabilityGraph.from_registry(root)
    task = TaskAnalyzer().analyze(args.text)
    pack = _load_pack_for_task(root, task)
    plan = TeamFormer(
        graph, memory=_load_memory_advisor(root, args), binding=_load_binding(root, task),
        objective=_resolve_objective(root, args), primary=_load_primary(root),
        preferences=pack.preferences if pack else None,
        limits=pack.limits if pack else None,
    ).form(task)
    print(json.dumps(plan.to_dict(), ensure_ascii=False, indent=2))
    return 0


def _cmd_run(args: argparse.Namespace) -> int:
    if args.mock and args.real:
        print("Error: choose either --mock or --real, not both.")
        return 2
    if not args.mock and not args.real:
        print("Error: specify --mock (offline) or --real (call authenticated CLIs).")
        return 2

    root = find_ammo_root()
    graph = CapabilityGraph.from_registry(root)
    task = TaskAnalyzer().analyze(args.text)
    pack = _load_pack_for_task(root, task)
    plan = TeamFormer(
        graph, memory=_load_memory_advisor(root, args), binding=_load_binding(root, task),
        objective=_resolve_objective(root, args), primary=_load_primary(root),
        preferences=pack.preferences if pack else None,
        limits=pack.limits if pack else None,
    ).form(task)

    if args.real:
        factory = RealAdapterFactory(root=root, allow_paid=args.allow_paid)
        mode = "real"
    else:
        factory = lambda model_id: MockAdapter(model_id)  # noqa: E731
        mode = "mock"
    result = Runner(factory, mode=mode).run(
        plan, task,
        system_context=(pack.context or "") if pack else "",
        role_context=_role_memory(root, plan.selected_system, plan.roles),
    )

    # tool execution + permission enforcement: workers' declared tools are gated
    # against the system's permissions.yaml + .ammoignore, then (safely) executed.
    tool_permitted = tool_denied = 0
    sandbox = None
    if plan.selected_system:
        try:
            import tempfile

            from ammo.tools import PermissionGate, Sandbox, ToolExecutor

            if args.execute_tools:
                sandbox_base = root / "runtime" / "sandbox"
                sandbox_base.mkdir(parents=True, exist_ok=True)
                sandbox = Sandbox(tempfile.mkdtemp(dir=str(sandbox_base)))

            tool_pack = pack or SystemPackLoader(root).load(plan.selected_system)
            executor = ToolExecutor(PermissionGate.from_pack(root, tool_pack), sandbox=sandbox)
            for response in result.responses:
                for evidence in executor.run_all(response.tool_requests):
                    response.evidence.append(evidence)
                    if evidence.ok:
                        tool_permitted += 1
                    else:
                        tool_denied += 1
        except RegistryError:
            pass

    report = ConfidenceEngine().assess(
        task, plan, result.responses, mode=result.mode,
        verification=pack.verification if pack else None,
    )

    # economics: estimate token usage + cost (api = spend, subscription =
    # equivalent value, local = 0) and feed it into the improvement loop.
    from ammo.economics import PricingBook

    economics = PricingBook.load(root).run_economics(result.responses)
    model_usage = {
        m["model"]: {"tokens": m["input_tokens"] + m["output_tokens"], "cost": m["cost"]}
        for m in economics["by_model"]
    }

    now = datetime.now(timezone.utc)
    run_id, path = RunStore(root).save(
        input_text=args.text, task=task, plan=plan, result=result,
        confidence=report.to_dict(), economics=economics,
        sandbox=str(sandbox.dir) if sandbox else None, now=now,
    )

    with MemoryStore.open(root) as memory:
        memory.record_run(
            run_id=run_id,
            timestamp=now.isoformat(),
            domain=task.domain,
            tags=task.tags,
            selected_system=plan.selected_system,
            model_ids=[m.model for m in plan.selected_team],
            team_signature=team_signature(plan),
            confidence_score=report.confidence_score,
            total_tokens=economics["total_tokens"],
            estimated_cost=economics["estimated_cost"],
            model_usage=model_usage,
        )

    # role-bound working directories: traces attach to the ROLE, not the model
    if plan.selected_system:
        workspace = RoleWorkspace(root)
        for resp in result.responses:
            workspace.record(
                plan.selected_system, resp.role,
                run_id=run_id, model=resp.model, output=resp.output,
                evidence=[e.to_dict() for e in resp.evidence],
                timestamp=now.isoformat(),
            )

    print(f"run_id: {run_id}")
    print(f"output: {path}")
    print(f"mode: {mode}")
    if args.real and getattr(factory, "resolutions", None):
        print(f"adapters: {factory.real_count}/{len(factory.resolutions)} real")
        for model_id, (kind, provider) in factory.resolutions.items():
            via = f" via {provider}" if kind == "real" and provider else ""
            print(f"  - {model_id}: {kind}{via}")
    print(f"system: {plan.selected_system}  team: {', '.join(plan.roles)}")
    if tool_permitted or tool_denied:
        print(f"tools: {tool_permitted} permitted, {tool_denied} denied (enforced)")
    if sandbox is not None:
        print(f"sandbox: {sandbox.dir}")
    print(
        f"economics: {economics['model_count']} model(s), "
        f"{economics['total_tokens']} tokens, "
        f"~${economics['estimated_cost']:.4f} {economics['currency']}"
        + (f"  [unpriced: {', '.join(economics['unpriced_models'])}]"
           if economics["unpriced_models"] else "")
    )
    print(f"confidence: {report.confidence_score} ({report.confidence_band})")
    # limits.yaml: the system's own acceptance threshold
    gate = (pack.limits or {}).get("confidence_gate") if pack else None
    if gate is not None and report.confidence_score < float(gate):
        escalation = (pack.limits or {}).get("escalation", "review")
        print(f"gate: below the system confidence_gate ({gate}) — escalation: {escalation}")
    print(f"final: {result.final_output}")

    if args.show_confidence:
        print()
        print(report.to_card())
    return 0


def _cmd_show_run(args: argparse.Namespace) -> int:
    store = RunStore(find_ammo_root())
    try:
        summary = store.load_summary(args.run_id)
    except FileNotFoundError:
        print(f"Error: run '{args.run_id}' not found under {store.runs_dir}")
        return 1
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


def _cmd_memory_help(_args: argparse.Namespace) -> int:
    print("Usage: ammo memory <stats|runs>")
    return 0


def _cmd_memory_stats(_args: argparse.Namespace) -> int:
    with MemoryStore.open(find_ammo_root()) as memory:
        stats = memory.stats()
    print(f"AMMO memory — runs: {stats['total_runs']}")
    if not stats["total_runs"]:
        print("(no runs recorded yet)")
        return 0
    print("by domain: " + ", ".join(f"{d}={n}" for d, n in stats["by_domain"].items()))
    print("models (by attempts):")
    for m in stats["models"]:
        rate = (m["successes"] / m["attempts"]) if m["attempts"] else 0.0
        print(
            f"  - {m['model_id']} [{m['task_tag']}]  attempts {m['attempts']}  "
            f"success {m['successes']} ({rate:.0%})  avg_conf {m['average_confidence']}"
        )
    print("teams (by attempts):")
    for t in stats["teams"]:
        print(
            f"  - {t['team_signature']} [{t['task_tag']}]  attempts {t['attempts']}  "
            f"success {t['successes']}  avg_conf {t['average_confidence']}"
        )
    return 0


def _cmd_memory_runs(args: argparse.Namespace) -> int:
    with MemoryStore.open(find_ammo_root()) as memory:
        runs = memory.list_runs(limit=args.limit)
    if not runs:
        print("(no runs recorded yet)")
        return 0
    print("recent runs:")
    for r in runs:
        print(
            f"  - {r['run_id']}  {r['timestamp']}  domain={r['domain']}  "
            f"system={r['selected_system']}  models={r['selected_models']}  "
            f"conf={r['confidence_score']}  outcome={r['outcome_status']}"
        )
    return 0


def main(argv: Optional[Sequence[str]] = None) -> int:
    """CLI entry point. Returns a process exit code."""
    parser = build_parser()
    args = parser.parse_args(argv)

    func = getattr(args, "func", None)
    if func is None:
        # No subcommand: show help and the philosophy. Exit 0 (not an error).
        parser.print_help()
        return 0

    return func(args)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
