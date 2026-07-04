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
        model = row["model"] or "(unset)"
        print(f"  {row['label']:<14} {model}")
    print("\nInternal kernel roles (auto — informational):")
    for row in roleplan.internal_mapping(assignments):
        if row["model"]:
            print(f"  {row['model']:<20} → {', '.join(row['internal_roles'])}")
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
        usable = _usable_models(getattr(args, "allow_paid", False))
        plans = roleplan.plan_roles(root, usable_models=usable, current=_load_roles(root))
        print("Role interview — for each seat type a number (or a model id), "
              "Enter for the ✓ default, or '-' to skip.\n")
        for p in plans:
            print(f"● {p.label} — {p.summary}")
            default = p.current or p.proposed
            for i, c in enumerate(p.candidates, 1):
                mark = "✓" if c["qualified"] else " "
                tags = f"[{c['cost']}/{c['latency']}{'/warm' if c['warm'] else ''}]"
                flag = "  ← default" if c["model"] == default else ""
                cur = "  (current)" if c["model"] == p.current else ""
                print(f"    {i}) {mark} {c['model']:<20} {tags}{flag}{cur}")
            answer = input(f"    → {p.label} [{default or 'skip'}]: ").strip()
            print()
            if answer == "-":
                continue
            choice = default
            if answer:
                if answer.isdigit() and 1 <= int(answer) <= len(p.candidates):
                    choice = p.candidates[int(answer) - 1]["model"]
                else:
                    choice = answer
            if choice:
                assignments[p.slot] = choice

    if not assignments:
        print("Nothing to set. Provide --orchestrator/--critic/--worker/--builder, "
              "or run in a terminal for the interactive interview.", file=sys.stderr)
        return 1

    config, warnings = roleplan.apply_roles(root, assignments)
    print("✓ Saved role assignment:")
    for row in roleplan.internal_mapping(config.roles):
        if row["model"]:
            print(f"  {row['label']:<14} {row['model']}")
    for w in warnings:
        print(f"  note: {w}")
    return 0
