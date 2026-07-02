"""ammo CLI handlers — provider cmds (split from cli.py)."""

import argparse
import sys
from typing import Optional, Sequence
from ammo.binding import (
    BindingStore,
    available_choices,
    build_binding,
    existing_or_best,
)
from ammo.paths import find_ammo_root
from ammo.roles import RoleWorkspace


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
