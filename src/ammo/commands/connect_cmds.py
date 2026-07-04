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


def _workspace_gate(root) -> Optional[str]:
    """Interactive workspace step: pick the directory AMMO will work in.

    Recommends previously-connected directories (kept as-is); otherwise asks for
    a path and connects it by reference (asking read-only vs read-write). Returns
    the system id in play, or None if skipped. Only ever acts on explicit input —
    filesystem access is never granted silently.
    """
    from ammo.connect import ConnectError, SystemConnector

    prior = _connected_dirs(root)
    print("Connect a directory for AMMO to work in (grants filesystem access).")
    if prior:
        print("  previously connected:")
        for i, (pid, sp) in enumerate(prior, 1):
            print(f"    {i}) {sp}   (as '{pid}')")
        ans = _prompt("  → keep one [number], type a new path, or '-' to skip: ")
    else:
        print("  none yet.")
        ans = _prompt("  → directory path to connect (or '-' to skip): ")

    if ans in ("-", "", "done", "skip"):
        print("  skipped — connect later with `ammo connect <path>`.\n")
        return prior[0][0] if (prior and ans == "") else None
    if ans.isdigit() and prior and 1 <= int(ans) <= len(prior):
        pid, sp = prior[int(ans) - 1]
        print(f"  keeping {sp}\n")
        return pid

    src = Path(ans).expanduser()
    if not src.is_dir():
        print(f"  '{src}' is not an existing directory — skipped.\n")
        return None
    writable = _ask_access()
    try:
        path = SystemConnector(root).connect(str(src), writable=(writable is True))
    except ConnectError as exc:
        print(f"  couldn't connect: {exc}\n")
        return None
    access = "read-write" if writable else "read-only"
    system_id = Path(path).name
    print(f"  ✓ connected {src}  ({access})")
    _ammoignore_gate(root, system_id, src)
    return system_id


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
