"""Interactive AMMO shell — `ammo enter` opens a session you stay inside.

Once entered, every line you type is an AMMO command (no `ammo` prefix): a bare
line is a `run`, or use any subcommand directly (`status`, `providers`,
`feedback <id> good`, ...). Session flags set once with `set` (real/mock,
optimize, read paths) apply to every subsequent run, so you configure once and
just work. `exit` (or `/ammo exit`, Ctrl-D) leaves.
"""

from __future__ import annotations

import shlex
from typing import List

BANNER = (
    "AMMO shell — you're inside. Type a request to run it; or a subcommand "
    "(status, providers, efficiency, feedback <id> good|bad, …).\n"
    "  set real|mock | set optimize <axis> | set read <path…> | set show on|off | "
    "set    (view)\n"
    "  help | exit  (or /ammo exit, Ctrl-D)"
)

_AXES = {"balanced", "performance", "cost", "speed"}


class Session:
    """Mutable per-session defaults applied to every bare run."""

    def __init__(self):
        self.mode = "real"          # real | mock
        self.optimize = None        # None | balanced | performance | cost | speed
        self.read: List[str] = []   # grounding paths
        self.show = False           # show the confidence card

    def describe(self) -> str:
        return (f"mode={self.mode}  optimize={self.optimize or 'default'}  "
                f"read={self.read or '—'}  show_confidence={'on' if self.show else 'off'}")

    def run_argv(self, text: str) -> List[str]:
        argv = ["run", f"--{self.mode}"]
        if self.optimize:
            argv += ["--optimize", self.optimize]
        if self.show:
            argv.append("--show-confidence")
        if self.read:
            argv += ["--read", *self.read]
        argv.append(text)
        return argv


def _apply_set(session: Session, args: List[str]) -> str:
    if not args:
        return session.describe()
    key, rest = args[0], args[1:]
    if key in ("real", "mock"):
        session.mode = key
    elif key == "optimize" and rest and rest[0] in _AXES:
        session.optimize = rest[0]
    elif key == "read":
        session.read = list(rest)          # `set read` with no path clears it
    elif key == "show" and rest and rest[0] in ("on", "off"):
        session.show = rest[0] == "on"
    else:
        return (f"unknown set: {' '.join(args)}\n"
                "  set real|mock | set optimize balanced|performance|cost|speed | "
                "set read <path…> | set show on|off")
    return session.describe()


def _read_line(prompt: str):
    try:
        return input(prompt)
    except (EOFError, KeyboardInterrupt):
        return None


def run_shell(dispatch, session: Session = None, read_line=_read_line) -> int:
    """Drive the interactive loop. `dispatch(argv) -> int` runs one AMMO command
    (injected so tests stay offline). `read_line` is injectable for testing."""
    from ammo import __version__

    session = session or Session()
    print(f"ammo {__version__} — {BANNER}")
    print(f"[{session.describe()}]")
    while True:
        line = read_line("ammo› ")
        if line is None:                    # Ctrl-D / interrupt
            print("\nleaving AMMO shell.")
            return 0
        line = line.strip()
        if not line:
            continue
        if line in ("exit", "quit", "/ammo exit", ":q"):
            print("leaving AMMO shell.")
            return 0
        if line in ("help", "?"):
            print(BANNER)
            continue
        try:
            parts = shlex.split(line)
        except ValueError as exc:
            print(f"parse error: {exc}")
            continue
        if parts[0] == "set":
            print(_apply_set(session, parts[1:]))
            continue
        # a bare request -> run with session defaults; an explicit subcommand
        # (status/providers/feedback/…) runs as typed
        if parts[0] in _SUBCOMMANDS:
            argv = parts
        else:
            argv = session.run_argv(line)
        try:
            dispatch(argv)
        except SystemExit:
            pass                            # a subcommand's arg error shouldn't kill the shell
    return 0


# subcommands that are meaningful inside the shell (typed verbatim); anything
# else is treated as a request to run
_SUBCOMMANDS = {
    "status", "providers", "efficiency", "feedback", "calibrate", "dream",
    "memory", "show-run", "doctor", "list-systems", "inspect-system",
    "plan-team", "analyze", "score-models", "list-models", "connect",
    "disconnect", "bind", "adopt", "new-system", "role-log", "eval",
    "promote", "pricing", "run", "start",
}


def _cmd_enter(args) -> int:
    from ammo.cli import build_parser

    def dispatch(argv):
        parsed = build_parser().parse_args(argv)
        func = getattr(parsed, "func", None)
        return func(parsed) if func else 0

    return run_shell(dispatch)
