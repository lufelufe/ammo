"""OS-level isolation for sandboxed commands.

On macOS this uses the native seatbelt (`sandbox-exec`) — verified live on
2026-07-02: writes outside the sandbox dir are denied by the kernel
("Operation not permitted"), network is denied (curl exit 6, socket
PermissionError), and writes inside the sandbox — including `git init` — work.

With OS isolation active the soft allowlist can be broadened to arbitrary
commands (except privilege escalation): the OS confines the blast radius —
no network, writes only inside the sandbox directory. Rule order matters in
SBPL: the LAST matching rule wins, so `deny file-write*` followed by
`allow file-write* (subpath ...)` confines writes to that subpath.
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path
from typing import Callable, List, Optional

SEATBELT = "seatbelt"

# never runnable, even under OS isolation
ESCALATION_COMMANDS = {"sudo", "su", "doas"}


def detect_isolation(which: Callable[[str], Optional[str]] = shutil.which,
                     platform: str = sys.platform) -> Optional[str]:
    """Best available OS-level isolation mechanism on this machine."""
    if platform == "darwin" and which("sandbox-exec"):
        return SEATBELT
    return None


def seatbelt_profile(workdir: Path) -> str:
    # `"` in a path would break the SBPL string; refuse rather than escape
    path = str(Path(workdir).resolve())
    if '"' in path:
        raise ValueError("sandbox dir path contains a quote")
    return (
        "(version 1)"
        "(allow default)"
        "(deny network*)"
        "(deny file-write*)"
        f'(allow file-write* (subpath "{path}"))'
        '(allow file-write* (subpath "/dev"))'
    )


def wrap_command(cmd: List[str], workdir: Path,
                 isolation: Optional[str]) -> List[str]:
    """Wrap `cmd` so the OS confines it; passthrough when no isolation."""
    if isolation == SEATBELT:
        return ["sandbox-exec", "-p", seatbelt_profile(workdir)] + list(cmd)
    return list(cmd)
