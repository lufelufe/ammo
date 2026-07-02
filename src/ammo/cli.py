"""AMMO command-line interface — the parser IS the UI surface.

All handler logic lives in ammo/commands/* (one module per concern);
this file only declares the command surface and dispatches.
"""

from __future__ import annotations

import argparse
import sys
from typing import Optional, Sequence

from ammo import __version__
from ammo.commands.inspect_cmds import _cmd_version, _cmd_doctor, _cmd_list_systems, _cmd_inspect_system
from ammo.commands.summon import _cmd_start, _cmd_status
from ammo.commands.kernel_cmds import _cmd_analyze, _cmd_list_models, _cmd_score_models, _cmd_plan_team
from ammo.commands.run_cmds import _cmd_run, _cmd_show_run, _cmd_promote
from ammo.commands.memory_cmds import _cmd_memory_help, _cmd_memory_stats, _cmd_memory_runs, _cmd_feedback, _cmd_calibrate, _cmd_dream
from ammo.commands.economics_cmds import _cmd_pricing_show, _cmd_pricing_set, _cmd_efficiency
from ammo.commands.eval_cmds import _cmd_eval, _cmd_eval_system, _cmd_eval_systems
from ammo.commands.connect_cmds import _cmd_new_system, _cmd_connect, _cmd_disconnect, _cmd_adopt
from ammo.commands.provider_cmds import _cmd_providers, _cmd_bind, _cmd_role_log

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
    run_parser.add_argument(
        "--consensus", type=int, nargs="?", const=2, default=0, metavar="N",
        help="Sample the lead seat with N independent models and have the "
             "checker measure agreement (bare flag = 2).",
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
    eval_suite_parser.add_argument(
        "--with-memory", action="store_true",
        help="Score decisions WITH accumulated run memory (learning mode) instead of the static baseline.",
    )
    eval_suite_parser.add_argument(
        "--compare", action="store_true",
        help="Diff the two most recent eval reports (trend) instead of running.",
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

    feedback_parser = subparsers.add_parser(
        "feedback", help="Record your verdict on a run (ground truth for learning).",
    )
    feedback_parser.add_argument("run_id", metavar="RUN_ID")
    feedback_parser.add_argument("verdict", choices=["good", "bad"])
    feedback_parser.add_argument("--note", default="", help="Optional short reason.")
    feedback_parser.set_defaults(func=_cmd_feedback)

    calibrate_parser = subparsers.add_parser(
        "calibrate", help="Compare confidence scores against user feedback (calibration).",
    )
    calibrate_parser.set_defaults(func=_cmd_calibrate)

    efficiency_parser = subparsers.add_parser(
        "efficiency", help="Quality-per-cost report from recorded runs.",
    )
    efficiency_parser.add_argument("--system", help="Limit to one system/tag.")
    efficiency_parser.set_defaults(func=_cmd_efficiency)

    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    """CLI entry point. Returns a process exit code."""
    parser = build_parser()
    args = parser.parse_args(argv)

    func = getattr(args, "func", None)
    if func is None:
        # No subcommand: show help and the philosophy. Exit 0 (not an error).
        parser.print_help()
        return 0

    try:
        return func(args)
    except (SystemExit, KeyboardInterrupt):
        raise
    except Exception as exc:  # triage: diagnose instead of dumping a traceback
        from ammo.triage import diagnose_exception

        print(diagnose_exception(exc).to_text(), file=sys.stderr)
        return 1



if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
