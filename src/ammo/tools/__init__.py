"""Tool execution + permission enforcement.

`PermissionGate` decides (default-deny) whether a tool call is allowed for a
system; `ToolExecutor` runs the safe, permitted ones and turns results into
Evidence. This is where declared tools become real actions — safely.
"""

from ammo.tools.executor import ToolExecutor
from ammo.tools.permissions import Decision, PermissionGate
from ammo.tools.sandbox import Sandbox, SandboxError

__all__ = ["PermissionGate", "ToolExecutor", "Decision", "Sandbox", "SandboxError"]
