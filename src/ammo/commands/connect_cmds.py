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


def _prompt(msg: str) -> str:
    """input() that treats end-of-input as skip (piped / non-tty friendly)."""
    try:
        return input(msg).strip()
    except (EOFError, OSError):
        return "-"


def _connected_dirs(root) -> list:
    """(system_id, source_path) for every already-connected external directory."""
    from ammo.registry import SystemPackLoader

    out = []
    try:
        for p in SystemPackLoader(root).load_all():
            if p.source_path:
                out.append((p.id, p.source_path))
    except Exception:
        pass
    return out


def _workspace_gate(root) -> list:
    """Interactive workspace step: connect one or more directories AMMO works in.

    Surfaces already-connected directories (previous sessions are recommended by
    being shown — type 'done' to keep them), then loops: enter a path, choose
    read-only/read-write, and (for a new dir) set .ammoignore. Returns the list of
    newly connected system ids. Only ever acts on explicit input — filesystem
    access is never granted silently.
    """
    from ammo.connect import ConnectError, SystemConnector

    print("Connect one or more directories for AMMO to work in (grants filesystem access).")
    newly: list = []
    while True:
        prior = _connected_dirs(root)
        if prior:
            print("  connected so far:")
            for pid, sp in prior:
                print(f"    • {sp}   (as '{pid}')")
        ans = _prompt("  → path to connect (or 'done' to finish): ")
        if ans in ("-", "", "done", "skip", "q"):
            break
        src = Path(ans).expanduser()
        if not src.is_dir():
            print(f"  '{src}' is not an existing directory.\n")
            continue
        writable = _ask_access()
        try:
            path = SystemConnector(root).connect(str(src), writable=(writable is True))
        except ConnectError as exc:
            print(f"  couldn't connect: {exc}\n")
            continue
        system_id = Path(path).name
        print(f"  ✓ connected {src}  ({'read-write' if writable else 'read-only'})")
        _ammoignore_gate(root, system_id, src)
        newly.append(system_id)

    if newly:
        print(f"  connected {len(newly)} new director"
              f"{'y' if len(newly) == 1 else 'ies'}.\n")
    elif not _connected_dirs(root):
        print("  none connected — do it later with `ammo connect <path>`.\n")
    else:
        print()
    return newly


# always worth protecting; matched by name/glob within the connected directory.
_ALWAYS_IGNORE = [".env", ".env.*", "*.key", "*.pem", "*.p12", "secrets/", ".git/"]
_NOISE_CANDIDATES = [
    "node_modules/", "__pycache__/", ".venv/", "venv/", "dist/", "build/",
    "target/", ".idea/", ".vscode/", ".mypy_cache/", ".pytest_cache/", ".DS_Store",
]


def _ammoignore_gate(root, system_id: str, source: Path) -> None:
    """Offer to exclude sensitive/noisy paths within a freshly-connected dir.

    Recommends secrets plus whatever noise dirs actually exist at the top level,
    and writes the chosen globs to the pack's .ammoignore (the permission gate
    then blocks those paths). Skipping leaves the commented default in place.
    """
    from ammo import pack_contract as pc

    try:
        present = {p.name for p in source.iterdir()}
    except OSError:
        present = set()
    noise = [c for c in _NOISE_CANDIDATES if c.rstrip("/") in present]
    recommended = _ALWAYS_IGNORE + noise

    print("  Exclude sensitive / noisy paths here (.ammoignore)?")
    print(f"    recommended: {', '.join(recommended)}")
    ans = _prompt("    [Y]es add these / [n]o / or type comma-separated globs: ")
    low = ans.lower()
    if low in ("n", "no", "-"):
        print("    left .ammoignore at its commented default.\n")
        return
    patterns = recommended if low in ("", "y", "yes") else \
        [p.strip() for p in ans.split(",") if p.strip()]
    if not patterns:
        print("    nothing to add.\n")
        return
    dest = root / "systems" / system_id / pc.IGNORE_FILE
    header = ("# Paths AMMO ignores within this system (one glob per line).\n"
              "# Written by the summon workspace step; edit freely.\n")
    dest.write_text(header + "\n".join(patterns) + "\n", encoding="utf-8")
    print(f"    ✓ excluding: {', '.join(patterns)}\n")


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
