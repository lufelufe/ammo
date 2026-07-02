"""Sandbox→real promotion: apply a run's sandboxed writes to the real target.

`--execute-tools` mirrors permitted `fs.write` calls into an isolated per-run
sandbox. Promotion is the reviewed second half: show the diff between each
sandboxed file and its real target (dry-run default), then `--apply` copies the
files after backing up anything overwritten into the run directory.

Safety:
- The target root comes from the system's `source_path` (connected systems) or
  an explicit `--to`; a system connected read-only is never promoted into.
- Every target path re-passes the system's PermissionGate (write scope +
  .ammoignore) at promotion time.
- Overwritten files are backed up under `<run_dir>/promote_backup/` first.
"""

from __future__ import annotations

import difflib
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

from ammo.kernel.executor import RunStore
from ammo.registry import SystemPackLoader
from ammo.tools.permissions import PermissionGate


class PromoteError(Exception):
    """Promotion refused (missing run/sandbox/target, or read-only system)."""


@dataclass
class FilePlan:
    relpath: str
    status: str          # new | modified | unchanged | denied
    diff: str = ""
    reason: str = ""


@dataclass
class PromotionReport:
    run_id: str
    target_root: str
    applied: bool = False
    files: List[FilePlan] = field(default_factory=list)
    backup_dir: str = ""

    def to_text(self) -> str:
        mode = "APPLIED" if self.applied else "DRY-RUN (use --apply to perform)"
        lines = [f"promote {self.run_id} -> {self.target_root} — {mode}"]
        for f in self.files:
            lines.append(f"  [{f.status}] {f.relpath}" + (f" — {f.reason}" if f.reason else ""))
            if f.diff and not self.applied:
                lines += ["    " + l for l in f.diff.splitlines()[:40]]
        if not self.files:
            lines.append("  (no sandboxed files to promote)")
        if self.backup_dir:
            lines.append(f"backup: {self.backup_dir}")
        return "\n".join(lines)


def _resolve_target_root(root: Path, system_id: str, to: Optional[str]) -> Path:
    if to:
        return Path(to).expanduser().resolve()
    pack = SystemPackLoader(root).load(system_id)
    source_path = pack.source_path
    if not source_path:
        raise PromoteError(
            "no target: the system has no source_path — pass --to <dir> explicitly"
        )
    if (pack.manifest or {}).get("writable") is False:
        raise PromoteError(
            f"system '{system_id}' is connected read-only; refusing to promote "
            "into its source (use --to for a different target)"
        )
    return Path(source_path).expanduser().resolve()


def plan_promotion(root: Path, run_id: str, to: Optional[str] = None,
                   apply: bool = False) -> PromotionReport:
    root = Path(root)
    store = RunStore(root)
    try:
        summary = store.load_summary(run_id)
    except FileNotFoundError:
        raise PromoteError(f"unknown run: {run_id}")

    sandbox_dir = summary.get("sandbox")
    if not sandbox_dir or not Path(sandbox_dir).is_dir():
        raise PromoteError(
            "this run has no sandbox (run with --execute-tools to produce one)"
        )
    system_id = summary.get("selected_system")
    if not system_id:
        raise PromoteError("run has no selected system")

    target_root = _resolve_target_root(root, system_id, to)
    pack = SystemPackLoader(root).load(system_id)
    gate = PermissionGate.from_pack(root, pack)

    sandbox_path = Path(sandbox_dir)
    report = PromotionReport(run_id=run_id, target_root=str(target_root))
    run_dir = store.run_path(run_id)
    backup_dir = run_dir / "promote_backup"

    for src in sorted(p for p in sandbox_path.rglob("*") if p.is_file()):
        relpath = str(src.relative_to(sandbox_path))
        target = target_root / relpath
        decision = gate.check("fs.write", {"path": str(target)})
        if not decision.allowed:
            report.files.append(FilePlan(relpath, "denied", reason=decision.reason))
            continue

        new_content = src.read_text(encoding="utf-8", errors="replace")
        if target.is_file():
            old_content = target.read_text(encoding="utf-8", errors="replace")
            if old_content == new_content:
                report.files.append(FilePlan(relpath, "unchanged"))
                continue
            diff = "\n".join(difflib.unified_diff(
                old_content.splitlines(), new_content.splitlines(),
                fromfile=f"real/{relpath}", tofile=f"sandbox/{relpath}", lineterm="",
            ))
            plan = FilePlan(relpath, "modified", diff=diff)
        else:
            plan = FilePlan(relpath, "new")

        if apply:
            if plan.status == "modified":
                backup_target = backup_dir / relpath
                backup_target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(target, backup_target)
                report.backup_dir = str(backup_dir)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, target)
        report.files.append(plan)

    report.applied = apply
    return report
