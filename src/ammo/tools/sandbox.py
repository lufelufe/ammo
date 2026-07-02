"""A soft sandbox for side-effecting tools.

Isolation via: a confined working directory (no path escape), a minimal
environment (no inherited secrets), a command **allowlist** of non-destructive,
no-network programs, and a timeout. This is NOT OS-level isolation
(container/namespace) — that is future work — but it makes `fs.write` and a small
set of `shell.run` commands safe to actually run and produce real Evidence.
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
    def __init__(self, base_dir: Path):
        self.dir = Path(base_dir).resolve()
        self.dir.mkdir(parents=True, exist_ok=True)

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

    def run(self, cmd: List[str], timeout: int = 10) -> Tuple[int, str]:
        if not cmd or cmd[0] not in SAFE_COMMANDS:
            raise SandboxError(f"command not in sandbox allowlist: {cmd[0] if cmd else '(empty)'}")
        try:
            proc = subprocess.run(
                cmd, cwd=str(self.dir), capture_output=True, text=True,
                timeout=timeout, env={"PATH": "/usr/bin:/bin"},
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
