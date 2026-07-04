"""ammo CLI handlers — role assignment (`ammo roles`).

The summoning host drives the interview UI; these commands are the data + apply
layer underneath it:

- ``ammo roles``          show the current assignment + auto internal-role map.
- ``ammo roles plan``     the interview data (usable models, candidates, defaults);
                          ``--json`` for a host to render as cards.
- ``ammo roles set ...``  persist an assignment (flags, or interactive in a tty).
"""

from __future__ import annotations

import argparse
import json
import sys

from ammo import roleplan
from ammo.paths import find_ammo_root


def _usable_models(allow_paid: bool = False):
    """Detected usable model ids (subscription/local first), or None to offer all."""
    try:
        from ammo.providers import DEFAULT_CATALOG, AvailabilityDetector, select_models

        statuses = AvailabilityDetector().detect_all(DEFAULT_CATALOG)
        usable = list(select_models(statuses, allow_paid=allow_paid))
        return usable or None
    except Exception:
        return None


def _load_roles(root):
    from ammo.config import load_config

    config = load_config(root)
    return dict(config.roles) if config else {}


def _prompt(msg: str) -> str:
    """input() that treats end-of-input as 'done' (piped / non-tty friendly).

    Also handles OSError (e.g. stdin unavailable / captured) so a non-interactive
    caller that reached the gate loop exits cleanly instead of crashing."""
    try:
        return input(msg).strip()
    except (EOFError, OSError):
        return "done"


def _gate_interview(root, *, statuses=None) -> dict:
    """The gate funnel: engine → (readiness) → model → role, member by member.

    Returns the accumulated {slot: model_id} assignment. Loops until the user is
    done; a not-ready engine drops into a resolve gate instead of proceeding.
    ``statuses`` (provider readiness) is reused from the caller when given.
    """
    engines = roleplan.team_engines(root, statuses=statuses)
    assignments = dict(_load_roles(root))
    print("Build your team — pick an engine, then its model, then the role it "
          "plays. Repeat for each seat.\n")

    while True:
        # Gate 1 — engine
        print("Gate 1 · engine:")
        for i, e in enumerate(engines, 1):
            status = "✓ ready" if e["ready"] else "· not ready"
            extra = (f"{len(e['models'])} model(s)" if e["ready"] and e["models"]
                     else (e["detail"] if not e["ready"] else "no models yet"))
            print(f"  {i}) {e['label']:<20} {status:<12} {extra}")
        filled = sum(1 for s in roleplan.SLOT_IDS if assignments.get(s))
        ans = _prompt(f"  → engine # (or 'done'; {filled}/4 seats filled): ").lower()
        if ans in ("done", "q", "quit", ""):
            break   # empty assignment is handled by the caller
        if not (ans.isdigit() and 1 <= int(ans) <= len(engines)):
            print("    (enter a number from the list)\n")
            continue
        eng = engines[int(ans) - 1]

        # Readiness gate — the engine must be logged in / prepared first
        if not eng["ready"]:
            print(f"\n  ⚠ {eng['label']} isn't ready — {eng['detail']}.")
            print(f"    fix: {eng['resolve']}")
            print("    resolve it and re-run, or choose a ready engine.\n")
            continue
        if not eng["models"]:
            print(f"\n  {eng['label']} is ready but has no models available.\n")
            continue

        # Gate 2 — model within the chosen engine
        print(f"\nGate 2 · model  ({eng['label']}):")
        for i, n in enumerate(eng["models"], 1):
            warm = "/warm" if n.warm_status == "warm" else ""
            print(f"  {i}) {roleplan.pretty(n.id):<22} [{n.cost_class}/{n.latency_class}{warm}]")
        ans = _prompt("  → model #: ")
        if not (ans.isdigit() and 1 <= int(ans) <= len(eng["models"])):
            print("    (enter a number)\n")
            continue
        model = eng["models"][int(ans) - 1]

        # Gate 3 — the role this engine·model plays
        print(f"\nGate 3 · role for {roleplan.pretty(model.id)}:")
        for i, s in enumerate(roleplan.SLOTS, 1):
            held = assignments.get(s["id"])
            note = f"   (now {roleplan.pretty(held)})" if held else ""
            print(f"  {i}) {s['label']:<16}{note}")
        ans = _prompt("  → role #: ")
        if not (ans.isdigit() and 1 <= int(ans) <= len(roleplan.SLOTS)):
            print("    (enter a number)\n")
            continue
        slot_id = roleplan.SLOTS[int(ans) - 1]["id"]
        assignments[slot_id] = model.id
        print(f"\n✓ {roleplan.pretty(model.id)} → {slot_id}\n")

        if all(assignments.get(s) for s in roleplan.SLOT_IDS):
            if _prompt("All four seats filled. Add/replace another? [y/N]: ").lower() \
                    not in ("y", "yes"):
                break
            print()
    return assignments


def _cmd_roles_show(_args: argparse.Namespace) -> int:
    root = find_ammo_root()
    assignments = _load_roles(root)
    if not assignments:
        print("No roles assigned yet.")
        print("Assign them: `ammo roles set` (interactive) or "
              "`ammo roles set --orchestrator ID --critic ID --worker ID --builder ID`.")
        print("In Claude Code, just say \"ammo\" and the host will ask you card by card.")
        return 0

    print("Role assignment (who plays which seat):")
    for row in roleplan.internal_mapping(assignments):
        model = roleplan.pretty(row["model"]) if row["model"] else "(unset)"
        print(f"  {row['label']:<14} {model}")
    print("\nInternal kernel roles (auto — informational):")
    for row in roleplan.internal_mapping(assignments):
        if row["model"]:
            print(f"  {roleplan.pretty(row['model']):<22} → {', '.join(row['internal_roles'])}")
    print(f"  {'(infra)':<20} → {', '.join(roleplan.INFRA_ROLES)} (test harness, auto)")

    warnings = roleplan.validate_assignments(assignments, root=root)
    if warnings:
        print("\nnotes:")
        for w in warnings:
            print(f"  - {w}")
    return 0


def _cmd_roles_plan(args: argparse.Namespace) -> int:
    root = find_ammo_root()
    usable = _usable_models(getattr(args, "allow_paid", False))
    plans = roleplan.plan_roles(root, usable_models=usable, current=_load_roles(root))

    if getattr(args, "json", False):
        payload = {
            "usable_models": usable,
            "slots": [
                {
                    "slot": p.slot, "label": p.label, "summary": p.summary,
                    "internal_roles": p.internal_roles, "proposed": p.proposed,
                    "current": p.current, "candidates": p.candidates,
                }
                for p in plans
            ],
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    print("Role interview — pick a model for each seat "
          f"(usable: {', '.join(usable) if usable else 'all registry models'}):\n")
    for p in plans:
        print(f"● {p.label} — {p.summary}")
        print(f"  internal roles: {', '.join(p.internal_roles)}")
        for c in p.candidates:
            mark = "✓" if c["qualified"] else "·"
            star = "  ← proposed" if c["model"] == p.proposed else ""
            cur = "  (current)" if c["model"] == p.current else ""
            print(f"    {mark} {c['model']:<20} [{c['cost']}/{c['latency']}"
                  f"{'/warm' if c['warm'] else ''}]{star}{cur}")
        print()
    print("Apply: ammo roles set --orchestrator ID --critic ID --worker ID --builder ID")
    return 0


def _cmd_roles_set(args: argparse.Namespace) -> int:
    root = find_ammo_root()
    flags = {
        "orchestrator": args.orchestrator, "critic": args.critic,
        "worker": args.worker, "builder": args.builder,
    }
    assignments = {k: v for k, v in flags.items() if v}

    interactive = not assignments and (getattr(args, "interactive", False)
                                       or sys.stdin.isatty())
    if interactive:
        assignments = _gate_interview(root)

    if not assignments:
        print("Nothing to set. Provide --orchestrator/--critic/--worker/--builder, "
              "or run in a terminal for the interactive interview.", file=sys.stderr)
        return 1

    config, warnings = roleplan.apply_roles(root, assignments)
    print("✓ Saved role assignment:")
    for row in roleplan.internal_mapping(config.roles):
        if row["model"]:
            print(f"  {row['label']:<14} {roleplan.pretty(row['model'])}")
    for w in warnings:
        print(f"  note: {w}")
    return 0
