"""A sandbox for side-effecting tools.

Two layers. Always: a confined working directory (no path escape), a minimal
environment (no inherited secrets), and a timeout. When **OS-level isolation**
is available (macOS seatbelt via `os_sandbox.py`), arbitrary commands —
including git — run kernel-confined (network denied, writes only inside the
sandbox dir) and the allowlist is bypassed (escalation commands stay banned).
Without OS isolation, `shell.run` falls back to a tiny allowlist of
non-destructive, no-network programs.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import List, Tuple

# non-destructive, no-network commands only. Deliberately tiny.
SAFE_COMMANDS = {"echo", "printf", "ls", "cat", "head", "tail", "wc", "pwd", "true"}


class SandboxError(Exception):
    """A sandbox operation was refused (escape attempt or disallowed command)."""


class Sandbox:
    def __init__(self, base_dir: Path, isolation: str = "auto"):
        """`isolation="auto"` detects OS-level confinement (macOS seatbelt);
        pass None to force the tiny soft allowlist only."""
        from ammo.tools.os_sandbox import detect_isolation

        self.dir = Path(base_dir).resolve()
        self.dir.mkdir(parents=True, exist_ok=True)
        self.isolation = detect_isolation() if isolation == "auto" else isolation

    def _confined(self, relpath: str) -> Path:
        target = (self.dir / relpath).resolve()
        if target != self.dir and self.dir not in target.parents:
            raise SandboxError(f"path escapes the sandbox: {relpath}")
        return target

    def write(self, relpath: str, content: str) -> Path:
        target = self._confined(relpath)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        return target

    def read(self, relpath: str) -> str:
        return self._confined(relpath).read_text(encoding="utf-8")

    def run(self, cmd: List[str], timeout: int = 30) -> Tuple[int, str]:
        from ammo.tools import os_sandbox

        if not cmd:
            raise SandboxError("command not in sandbox allowlist: (empty)")
        if cmd[0] in os_sandbox.ESCALATION_COMMANDS:
            raise SandboxError(f"privilege escalation is never permitted: {cmd[0]}")

        if self.isolation:
            # OS confines the blast radius (no network, writes only inside the
            # sandbox), so arbitrary commands — including git — become runnable.
            full = os_sandbox.wrap_command(cmd, self.dir, self.isolation)
            tmp = self.dir / ".tmp"
            tmp.mkdir(exist_ok=True)
            env = {"PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
                   "HOME": str(self.dir), "TMPDIR": str(tmp)}
        else:
            if cmd[0] not in SAFE_COMMANDS:
                raise SandboxError(f"command not in sandbox allowlist: {cmd[0]}")
            full = list(cmd)
            env = {"PATH": "/usr/bin:/bin"}

        try:
            proc = subprocess.run(
                full, cwd=str(self.dir), capture_output=True, text=True,
                timeout=timeout, env=env,
            )
        except subprocess.TimeoutExpired:
            return 124, "(timeout)"
        except OSError as exc:
            return 127, str(exc)
        return proc.returncode, (proc.stdout + proc.stderr)

    def files(self) -> List[str]:
        return sorted(
            str(p.relative_to(self.dir)) for p in self.dir.rglob("*") if p.is_file()
        )
