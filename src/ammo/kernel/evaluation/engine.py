"""System-level evaluation.

Aggregates what AMMO already knows about a system — contract validity, capability
coverage, optimization-spec completeness, and run history from memory — into a
health verdict with concrete improvements and problems. Reads only; changes
nothing.
"""

from __future__ import annotations

from pathlib import Path
from typing import List, Optional

from ammo.kernel.capability_graph import CapabilityGraph
from ammo.kernel.evaluation.report import EvaluationReport
from ammo.registry import RegistryError, SystemPackLoader

_DEFAULT_GATE = 0.6


class EvaluationEngine:
    def evaluate(self, root: Path, system_id: str,
                 graph: Optional[CapabilityGraph] = None) -> EvaluationReport:
        root = Path(root)
        loader = SystemPackLoader(root)

        try:
            pack = loader.load(system_id)
        except RegistryError as exc:
            return EvaluationReport(system_id, "at_risk", problems=[f"contract invalid: {exc}"])

        works: List[str] = ["contract valid"]
        improvements: List[str] = []
        problems: List[str] = []

        # 1. optimization specs present?
        specs = {
            "preferences.yaml": bool(pack.preferences),
            "verification.yaml": bool(pack.verification),
            "limits.yaml": bool(pack.limits),
            "context.md": pack.context is not None,
        }
        for name, present in specs.items():
            if present:
                works.append(f"{name} defined")
            else:
                improvements.append(f"add {name} to optimize this system")

        # 2. mounted source still exists?
        if pack.source_path and not Path(pack.source_path).is_dir():
            problems.append(f"mounted source path missing: {pack.source_path}")

        # 3. capability coverage: every referenced role / preferred capability must
        #    be fillable by some enabled model.
        graph = graph or CapabilityGraph.from_registry(root)
        for role in sorted(pack.referenced_roles()):
            if not graph.by_role(role):
                problems.append(f"no enabled model can fill role '{role}'")
        for capability in pack.preferences.get("preferred_capabilities", []) or []:
            if not graph.by_capability(capability):
                problems.append(f"no enabled model provides preferred capability '{capability}'")

        # 4. run history from memory
        runs = self._runs(root, system_id)
        stats = {"specs": specs, "runs": len(runs)}
        gate = (pack.limits or {}).get("confidence_gate", _DEFAULT_GATE)
        if not runs:
            improvements.append("no runs recorded yet — exercise the system to gather signal")
        else:
            scores = [r["confidence_score"] or 0.0 for r in runs]
            successes = sum(1 for s in scores if s >= 0.5)
            rate = round(successes / len(runs), 3)
            avg = round(sum(scores) / len(runs), 3)
            stats.update(success_rate=rate, average_confidence=avg, confidence_gate=gate)
            works.append(f"{len(runs)} run(s), {rate:.0%} success, avg confidence {avg}")
            if avg < gate:
                improvements.append(
                    f"average confidence {avg} below gate {gate} — strengthen team or evidence"
                )
            # recurring negative confidence reasons -> sharp, specific suggestions
            counts: dict = {}
            for run in runs:
                for reason in set(run.get("negative_reasons") or []):
                    counts[reason] = counts.get(reason, 0) + 1
            for reason, n in sorted(counts.items(), key=lambda kv: -kv[1])[:3]:
                if n >= 2 and n * 2 >= len(runs):        # in at least half the runs
                    improvements.append(
                        f"recurring issue ({n}/{len(runs)} runs): {reason}"
                    )

        health = self._health(problems, runs, stats)
        return EvaluationReport(system_id, health, works, improvements, problems, stats)

    def _runs(self, root: Path, system_id: str):
        db = Path(root) / "memory" / "ammo.sqlite"
        if not db.is_file():
            return []
        from ammo.memory import MemoryStore

        with MemoryStore(db) as memory:
            return memory.runs_for_system(system_id)

    def _health(self, problems, runs, stats) -> str:
        if problems:
            return "at_risk"
        if not runs:
            return "unproven"
        below_gate = stats.get("average_confidence", 0.0) < stats.get("confidence_gate", _DEFAULT_GATE)
        if stats.get("success_rate", 0.0) >= 0.6 and not below_gate:
            return "healthy"
        return "ok"
