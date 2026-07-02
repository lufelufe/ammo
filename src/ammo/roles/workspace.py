"""Role-bound working directories.

Every role gets a persistent workspace **per system**, at
``systems/<system>/roles/<role>/``. Traces and data are bound to the ROLE, not
the model — so a role accumulates context/history even as the model filling it
changes. This supports independent + collaborative work and honest per-role
attribution. Contents are runtime data (gitignored).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

JOURNAL = "journal.jsonl"
LAST = "last.md"


class RoleWorkspace:
    def __init__(self, root: Path):
        self.root = Path(root)

    def path(self, system: str, role: str) -> Path:
        return self.root / "systems" / system / "roles" / role

    def ensure(self, system: str, role: str) -> Path:
        path = self.path(system, role)
        path.mkdir(parents=True, exist_ok=True)
        return path

    def record(
        self,
        system: str,
        role: str,
        *,
        run_id: str,
        model: str,
        output: str,
        evidence: Optional[List[Dict[str, Any]]] = None,
        timestamp: str = "",
    ) -> Path:
        """Append one turn to the role's journal (bound to role, notes the model)."""
        path = self.ensure(system, role)
        entry = {
            "run_id": run_id,
            "timestamp": timestamp,
            "model": model,           # which model filled the role this time
            "output": output,
            "evidence": evidence or [],
        }
        with (path / JOURNAL).open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
        (path / LAST).write_text(
            f"# {role} — last output ({run_id})\n\n{output}\n", encoding="utf-8"
        )
        return path

    def journal(self, system: str, role: str) -> List[Dict[str, Any]]:
        path = self.path(system, role) / JOURNAL
        if not path.is_file():
            return []
        entries = []
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                entries.append(json.loads(line))
        return entries

    def roles(self, system: str) -> List[str]:
        base = self.root / "systems" / system / "roles"
        if not base.is_dir():
            return []
        return sorted(p.name for p in base.iterdir() if p.is_dir())
