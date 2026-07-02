"""Execute a worker's declared tool requests — through the permission gate.

v0 actually runs only **safe, read-only** tools (`fs.read`, `doc.read`) and turns
their result into Evidence. Everything else that passes the gate is recorded as
"permitted (not executed)" — dangerous side-effecting tools (fs.write, shell.run,
git, network) wait for a sandboxed step. Denied calls become failed Evidence.
"""

from __future__ import annotations

import shlex
from pathlib import Path
from typing import List, Optional

from ammo.adapters.contract import Evidence, ToolRequest
from ammo.tools.permissions import PermissionGate, READ_TOOLS
from ammo.tools.sandbox import Sandbox, SandboxError


class ToolExecutor:
    def __init__(self, gate: PermissionGate, sandbox: Optional[Sandbox] = None):
        self.gate = gate
        self.sandbox = sandbox

    def execute(self, request: ToolRequest) -> Evidence:
        decision = self.gate.check(request.tool, request.args)
        if not decision.allowed:
            return Evidence(kind="tool", summary=f"{request.tool} denied", ok=False,
                            detail=decision.reason)

        if request.tool in READ_TOOLS:
            return self._read(request)

        # side-effecting tools: execute in the sandbox if one is provided
        if self.sandbox is not None:
            if request.tool == "fs.write":
                return self._sandbox_write(request)
            if request.tool == "shell.run":
                return self._sandbox_shell(request)

        # permitted, but no sandbox / not yet sandbox-executable (git, network)
        return Evidence(kind="tool", summary=f"{request.tool} permitted", ok=True,
                        detail="not executed (awaiting sandboxed execution)")

    def _sandbox_write(self, request: ToolRequest) -> Evidence:
        raw = request.args.get("path") or request.args.get("target") or "output"
        content = request.args.get("content", "")
        relpath = Path(raw).name if Path(raw).is_absolute() else raw
        try:
            written = self.sandbox.write(relpath, content)
        except SandboxError as exc:
            return Evidence(kind="fs_write", summary="fs.write blocked", ok=False, detail=str(exc))
        return Evidence(kind="fs_write",
                        summary=f"wrote {written.name} ({len(content)} bytes) in sandbox",
                        ok=True, detail=str(written))

    def _sandbox_shell(self, request: ToolRequest) -> Evidence:
        cmd = request.args.get("cmd") or request.args.get("command")
        if isinstance(cmd, str):
            cmd = shlex.split(cmd)
        if not cmd:
            return Evidence(kind="shell", summary="shell.run: no command", ok=False)
        try:
            code, output = self.sandbox.run(cmd)
        except SandboxError as exc:
            return Evidence(kind="shell", summary="shell.run blocked", ok=False, detail=str(exc))
        return Evidence(kind="shell", summary=f"ran '{cmd[0]}' (exit {code})",
                        ok=(code == 0), detail=output[:500])

    def _read(self, request: ToolRequest) -> Evidence:
        raw = request.args.get("path") or request.args.get("target")
        target = Path(raw)
        target = target if target.is_absolute() else (self.gate.root / raw)
        if not target.is_file():
            return Evidence(kind="file_read", summary=f"{request.tool}: file not found", ok=False,
                            detail=str(target))
        try:
            size = len(target.read_bytes())
        except OSError as exc:
            return Evidence(kind="file_read", summary=f"{request.tool}: read failed", ok=False,
                            detail=str(exc))
        return Evidence(kind="file_read", summary=f"read {target.name} ({size} bytes)", ok=True,
                        detail=str(target))

    def run_all(self, requests: List[ToolRequest]) -> List[Evidence]:
        return [self.execute(r) for r in requests]
