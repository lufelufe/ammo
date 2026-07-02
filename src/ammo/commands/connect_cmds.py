"""ammo CLI handlers — connect cmds (split from cli.py)."""

import argparse
from pathlib import Path
import sys
from typing import Optional, Sequence
from ammo.connect import ConnectError, SystemConnector
from ammo.paths import find_ammo_root


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

    root = find_ammo_root()
    connector = SystemConnector(root)
    source = Path(args.path).expanduser().resolve()
    if source == root.resolve() or root.resolve() in source.parents:
        print("warning: the source is INSIDE the AMMO root — nested mounts are "
              "confusing; prefer `ammo new-system` for internal packs.")
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
