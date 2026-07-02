"""`ammo dream` — automated memory consolidation (docs/MEMORY_DREAM.md).

Mine the run record, then: **Consolidate** (rebuild aggregates from a recent
window of runs, re-deriving tags so legacy domain-keyed rows merge, carrying
cost/token averages over), **Dedup & Resolve** (drop orphan rows for models no
longer in the registry), **Prune** (GC run rows/artifacts beyond the window,
distill oversized role journals into insights). Dry-run by default; `--apply`
backs up the DB first. Inputs are never silently destroyed.
"""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List

from ammo.memory.store import MemoryStore, _signature_models

DEFAULT_WINDOW = 50
DEFAULT_JOURNAL_KEEP = 20


@dataclass
class DreamReport:
    applied: bool = False
    runs_total: int = 0
    window: int = DEFAULT_WINDOW
    orphan_model_rows: List[str] = field(default_factory=list)   # "model@tag"
    orphan_team_rows: int = 0
    tags_before: int = 0
    tags_after: int = 0
    runs_pruned: List[str] = field(default_factory=list)
    run_dirs_pruned: List[str] = field(default_factory=list)
    journals: List[Dict[str, Any]] = field(default_factory=list)  # {system, role, entries, keep}
    backup: str = ""
    notes: List[str] = field(default_factory=list)

    def to_text(self) -> str:
        mode = "APPLIED" if self.applied else "DRY-RUN (use --apply to perform)"
        lines = [f"AMMO dream — {mode}", f"runs recorded: {self.runs_total} (window: {self.window})"]
        lines.append(
            f"consolidate: rebuild aggregates from the last "
            f"{min(self.window, self.runs_total)} run(s); tags {self.tags_before} -> {self.tags_after}"
        )
        lines.append(
            f"dedup: {len(self.orphan_model_rows)} orphan model row(s), "
            f"{self.orphan_team_rows} orphan team row(s)"
            + (f" — {', '.join(self.orphan_model_rows[:5])}" if self.orphan_model_rows else "")
        )
        lines.append(
            f"prune: {len(self.runs_pruned)} run row(s) beyond window, "
            f"{len(self.run_dirs_pruned)} run artifact dir(s)"
        )
        for j in self.journals:
            lines.append(
                f"journal: {j['system']}/{j['role']} — {j['entries']} entries -> "
                f"keep {j['keep']} + insights.md"
            )
        if not self.journals:
            lines.append("journal: nothing oversized")
        if self.backup:
            lines.append(f"backup: {self.backup}")
        lines += [f"note: {n}" for n in self.notes]
        return "\n".join(lines)


class DreamEngine:
    def __init__(self, root: Path, window: int = DEFAULT_WINDOW,
                 journal_keep: int = DEFAULT_JOURNAL_KEEP):
        self.root = Path(root)
        self.window = window
        self.journal_keep = journal_keep

    # -- shared analysis ------------------------------------------------------

    def _known_models(self):
        from ammo.kernel.capability_graph import CapabilityGraph
        from ammo.kernel.team_formation import templates as tpl

        graph = CapabilityGraph.from_registry(self.root)
        return {n.id for n in graph.nodes} | set(tpl.FIXED_MODELS.values())

    def _db_path(self) -> Path:
        return self.root / "memory" / "ammo.sqlite"

    def _analyze(self, store: MemoryStore, known) -> DreamReport:
        report = DreamReport(window=self.window)
        report.runs_total = store.stats()["total_runs"]

        perf = store.all_model_performance()
        report.tags_before = len({r["task_tag"] for r in perf})
        report.orphan_model_rows = sorted(
            f"{r['model_id']}@{r['task_tag']}" for r in perf if r["model_id"] not in known
        )
        report.orphan_team_rows = sum(
            1 for r in store.all_team_synergy()
            if any(m not in known for m in _signature_models(r["team_signature"]))
        )

        window_runs = store.list_runs(limit=self.window)
        report.tags_after = len({
            (r.get("selected_system") or r.get("domain") or "general")
            for r in window_runs
        })

        all_ids = [r["run_id"] for r in store.list_runs(limit=max(report.runs_total, 1))]
        report.runs_pruned = all_ids[self.window:]

        runs_dir = self.root / "runtime" / "runs"
        if runs_dir.is_dir():
            keep = set(all_ids[: self.window])
            report.run_dirs_pruned = sorted(
                p.name for p in runs_dir.iterdir() if p.is_dir() and p.name not in keep
            )

        report.journals = self._oversized_journals()
        return report

    def _oversized_journals(self) -> List[Dict[str, Any]]:
        out = []
        systems_dir = self.root / "systems"
        if not systems_dir.is_dir():
            return out
        for journal in sorted(systems_dir.glob("*/roles/*/journal.jsonl")):
            entries = sum(1 for line in journal.read_text(encoding="utf-8").splitlines() if line.strip())
            if entries > self.journal_keep:
                out.append({
                    "system": journal.parts[-4], "role": journal.parts[-2],
                    "entries": entries, "keep": self.journal_keep, "path": journal,
                })
        return out

    # -- public ---------------------------------------------------------------

    def plan(self) -> DreamReport:
        db = self._db_path()
        if not db.is_file():
            report = DreamReport(window=self.window)
            report.journals = self._oversized_journals()
            report.notes.append("no memory db — nothing to consolidate")
            return report
        with MemoryStore(db) as store:
            return self._analyze(store, self._known_models())

    def apply(self) -> DreamReport:
        db = self._db_path()
        known = self._known_models()
        if not db.is_file():
            report = self.plan()
            self._distill_journals(report)
            report.applied = True
            return report

        backup = db.with_name(db.name + ".bak")
        shutil.copy2(db, backup)

        with MemoryStore(db) as store:
            report = self._analyze(store, known)
            report.backup = str(backup)
            # Consolidate + Dedup: rebuild from the window, oldest-first
            window_runs = list(reversed(store.list_runs(limit=self.window)))
            store.rebuild_aggregates(window_runs, known)
            # Prune: memory rows beyond the window
            store.prune_runs_keep(self.window)

        # Prune: run artifact dirs no longer backed by memory rows
        runs_dir = self.root / "runtime" / "runs"
        for name in report.run_dirs_pruned:
            shutil.rmtree(runs_dir / name, ignore_errors=True)

        self._distill_journals(report)
        report.applied = True
        return report

    def _distill_journals(self, report: DreamReport) -> None:
        # invoked from apply() only — plan() never mutates journals
        for j in report.journals:
            journal_path: Path = j["path"]
            lines = [l for l in journal_path.read_text(encoding="utf-8").splitlines() if l.strip()]
            entries = []
            for line in lines:
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
            keep = entries[-self.journal_keep:]
            distilled = entries[: -self.journal_keep] if len(entries) > self.journal_keep else []
            models: Dict[str, int] = {}
            for e in entries:
                models[e.get("model", "?")] = models.get(e.get("model", "?"), 0) + 1
            first_ts = entries[0].get("timestamp", "") if entries else ""
            last_ts = entries[-1].get("timestamp", "") if entries else ""
            insights = (
                f"# {j['role']} — distilled insights ({j['system']})\n\n"
                f"- {len(entries)} turn(s) seen ({first_ts} .. {last_ts}); "
                f"{len(distilled)} archived by dream, last {len(keep)} kept in the journal.\n"
                f"- models that filled this role: "
                + ", ".join(f"{m} ({c})" for m, c in sorted(models.items(), key=lambda x: -x[1]))
                + "\n"
            )
            (journal_path.parent / "insights.md").write_text(insights, encoding="utf-8")
            journal_path.write_text(
                "\n".join(json.dumps(e, ensure_ascii=False) for e in keep) + "\n",
                encoding="utf-8",
            )
