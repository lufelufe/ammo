"""Grounding — read real files into a worker's context BEFORE it answers.

The gap P1 closes: workers used to answer analysis/repo questions with no
access to the actual files, so they hallucinated and the Confidence Engine
honestly capped them ("no evidence produced"). Grounding gathers a bounded,
relevant slice of real file content and hands it to every worker as context,
and emits real `file_read` Evidence so trust is earned from what was actually
read.

Deterministic and bounded: text files only, a fixed relevance order, and a hard
character budget (truncation is disclosed, never silent). When a system is
selected its PermissionGate authorizes every read (write scope is irrelevant —
reading only); an explicit user-pointed path is read directly (the user's own
files, their choice).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Tuple

from ammo.adapters.contract import Evidence

DEFAULT_BUDGET = 12000        # chars of file content injected (bounded context)
_PER_FILE_CAP = 4000          # no single file dominates the budget
_MAX_FILES = 40

# read these; in this priority order (docs/specs first, then code, then data)
_TEXT_SUFFIXES = {".md", ".py", ".yaml", ".yml", ".txt", ".json", ".toml", ".cfg", ".ini", ".sh"}
_PRIORITY = [".md", ".yaml", ".yml", ".toml", ".py", ".json", ".txt", ".cfg", ".ini", ".sh"]

# never walk into these (noise / large / private)
_SKIP_DIRS = {".git", ".venv", "venv", "node_modules", "__pycache__",
              "runtime", "memory", "vaults", ".claude", ".claude-b",
              "dist", "build", ".pytest_cache", ".mypy_cache"}


@dataclass
class Grounding:
    text: str = ""
    evidence: List[Evidence] = field(default_factory=list)
    files_read: List[str] = field(default_factory=list)
    truncated: bool = False

    @property
    def empty(self) -> bool:
        return not self.text


def _rank(path: Path) -> Tuple[int, str]:
    try:
        idx = _PRIORITY.index(path.suffix.lower())
    except ValueError:
        idx = len(_PRIORITY)
    return (idx, str(path))


def _iter_text_files(target: Path) -> List[Path]:
    if target.is_file():
        return [target] if target.suffix.lower() in _TEXT_SUFFIXES else []
    out: List[Path] = []
    for path in sorted(target.rglob("*")):
        if not path.is_file():
            continue
        if any(part in _SKIP_DIRS for part in path.parts):
            continue
        if path.suffix.lower() in _TEXT_SUFFIXES:
            out.append(path)
    out.sort(key=_rank)
    return out


def gather(paths: List[str], root: Path, gate=None,
           budget: int = DEFAULT_BUDGET) -> Grounding:
    """Read a bounded slice of `paths` (files/dirs) into a Grounding bundle.

    `gate` (a PermissionGate) authorizes each read when a system is selected;
    without it, explicit user-pointed paths are read directly.
    """
    root = Path(root)
    result = Grounding()
    used = 0
    seen = set()

    for raw in paths:
        target = Path(raw)
        target = target if target.is_absolute() else (root / raw)
        target = target.resolve()
        for path in _iter_text_files(target):
            if used >= budget or len(result.files_read) >= _MAX_FILES:
                result.truncated = True
                break
            if path in seen:
                continue
            seen.add(path)

            if gate is not None:
                decision = gate.check("fs.read", {"path": str(path)})
                if not decision.allowed:
                    result.evidence.append(Evidence(
                        "file_read", f"read denied: {path.name}", ok=False,
                        detail=decision.reason))
                    continue
            try:
                content = path.read_text(encoding="utf-8", errors="replace")
            except OSError as exc:
                result.evidence.append(Evidence(
                    "file_read", f"read failed: {path.name}", ok=False, detail=str(exc)))
                continue

            snippet = content[:_PER_FILE_CAP]
            if len(content) > _PER_FILE_CAP:
                snippet += "\n… (file truncated)"
            remaining = budget - used
            if len(snippet) > remaining:
                snippet = snippet[:remaining] + "\n… (budget reached)"
                result.truncated = True
            try:
                rel = path.relative_to(root)
            except ValueError:
                rel = path
            result.text += f"\n===== {rel} =====\n{snippet}\n"
            used += len(snippet)
            result.files_read.append(str(rel))
            result.evidence.append(Evidence(
                "file_read", f"read {rel} ({len(content)} bytes)", ok=True,
                detail=str(rel)))
        if result.truncated:
            break

    if result.text:
        header = (f"Files read for grounding ({len(result.files_read)} file(s)"
                  f"{', truncated to budget' if result.truncated else ''}). "
                  "Base your answer on this real content, not assumptions:\n")
        result.text = header + result.text
    return result
