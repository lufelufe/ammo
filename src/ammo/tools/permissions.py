"""Permission enforcement — the gate every tool call must pass.

Default-deny. A tool call is allowed only if the system's `permissions.yaml`
permits the tool, the network (for network tools), and the path (for filesystem
tools) — within the declared read/write scopes and not matched by `.ammoignore`.
This is what makes a "connected" pack safe to actually act on.
"""

from __future__ import annotations

from dataclasses import dataclass
from fnmatch import fnmatch
from pathlib import Path
from typing import List, Optional

from ammo import pack_contract as pc

NETWORK_TOOLS = {"web.search", "web.fetch"}
READ_TOOLS = {"fs.read", "doc.read"}
WRITE_TOOLS = {"fs.write"}
PATH_TOOLS = READ_TOOLS | WRITE_TOOLS


@dataclass
class Decision:
    allowed: bool
    reason: str


def _within(child: Path, parent: Path) -> bool:
    try:
        child.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def _resolve(scopes: List[str], root: Path, source_path: Optional[str]) -> List[Path]:
    resolved = []
    for scope in scopes:
        p = Path(scope)
        resolved.append(p if p.is_absolute() else (root / scope))
    return resolved


def _load_ammoignore(pack_path: Path) -> List[str]:
    path = pack_path / pc.IGNORE_FILE
    if not path.is_file():
        return []
    patterns = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            patterns.append(line.rstrip("/"))
    return patterns


class PermissionGate:
    def __init__(self, root: Path, *, read_scopes, write_scopes, network: bool,
                 allowed_tools, ammoignore, source_path: Optional[str] = None):
        self.root = Path(root)
        self.network = network
        self.allowed_tools = set(allowed_tools)
        self.ammoignore = list(ammoignore)
        self.write_scopes = _resolve(write_scopes, self.root, source_path)
        # write scopes are also readable
        self.read_scopes = _resolve(read_scopes, self.root, source_path) + self.write_scopes

    @classmethod
    def from_pack(cls, root: Path, pack) -> "PermissionGate":
        perms = pack.permissions or {}
        fs = perms.get("filesystem") or {}
        return cls(
            root,
            read_scopes=fs.get("read") or [],
            write_scopes=fs.get("write") or [],
            network=bool((perms.get("network") or {}).get("allow", False)),
            allowed_tools=(perms.get("tools") or {}).get("allow", []),
            ammoignore=_load_ammoignore(pack.path),
            source_path=pack.source_path,
        )

    def _ignored(self, path: Path) -> bool:
        parts = set(path.parts)
        for pattern in self.ammoignore:
            if fnmatch(path.name, pattern) or pattern in parts or fnmatch(str(path), pattern):
                return True
        return False

    def check(self, tool: str, args: Optional[dict] = None) -> Decision:
        args = args or {}
        if tool not in self.allowed_tools:
            return Decision(False, f"tool '{tool}' not in permissions.tools.allow")
        if tool in NETWORK_TOOLS and not self.network:
            return Decision(False, "network is not permitted for this system")
        if tool in PATH_TOOLS:
            raw = args.get("path") or args.get("target")
            if not raw:
                return Decision(False, "no path provided")
            target = Path(raw)
            target = target if target.is_absolute() else (self.root / raw)
            scopes = self.write_scopes if tool in WRITE_TOOLS else self.read_scopes
            if not any(_within(target, s) for s in scopes):
                return Decision(False, f"path outside permitted {'write' if tool in WRITE_TOOLS else 'read'} scope")
            if self._ignored(target):
                return Decision(False, "path is excluded by .ammoignore")
        return Decision(True, "permitted")
