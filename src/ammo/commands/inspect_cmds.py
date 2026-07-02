"""ammo CLI handlers — inspect cmds (split from cli.py)."""

import argparse
from ammo import __version__
from ammo.doctor import run_doctor
from ammo.paths import find_ammo_root
from ammo.registry import RegistryError, SystemPackLoader, enabled_systems


def _cmd_version(_args: argparse.Namespace) -> int:
    print(f"ammo {__version__}")
    return 0


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
