"""Run eval cases through AMMO and score the five metrics.

Deterministic, static baseline: no memory, no binding — so a report reflects the
kernel's current decisions and can be compared across changes to see whether
AMMO is improving. Mock execution only; no real models.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from ammo.adapters import MockAdapter
from ammo.evalsuite.case import EvalCase
from ammo.kernel.capability_graph import CapabilityGraph
from ammo.kernel.confidence import ConfidenceEngine
from ammo.kernel.executor import Runner
from ammo.kernel.task_understanding import TaskAnalyzer
from ammo.kernel.team_formation import TeamFormer

DEFAULT_POLICY = "require real execution before applying changes"
_BAND_ORDER = {"very_low": 0, "low": 1, "medium": 2, "high": 3}

METRICS = (
    "selected_system_correct",
    "selected_team_correct",
    "confidence_reasonable",
    "required_tools_detected",
    "policy_decision_correct",
)


@dataclass
class CaseResult:
    id: str
    metrics: Dict[str, bool]
    observed: Dict[str, Any] = field(default_factory=dict)

    @property
    def passed(self) -> bool:
        return all(self.metrics.values())


@dataclass
class SuiteReport:
    results: List[CaseResult] = field(default_factory=list)

    @property
    def all_passed(self) -> bool:
        return all(r.passed for r in self.results)

    @property
    def cases_passed(self) -> int:
        return sum(1 for r in self.results if r.passed)

    def metric_totals(self) -> Dict[str, Dict[str, int]]:
        totals = {m: {"passed": 0, "total": 0} for m in METRICS}
        for result in self.results:
            for metric, ok in result.metrics.items():
                totals[metric]["total"] += 1
                totals[metric]["passed"] += 1 if ok else 0
        return totals

    def to_dict(self) -> Dict[str, Any]:
        return {
            "cases_passed": self.cases_passed,
            "cases_total": len(self.results),
            "metric_totals": self.metric_totals(),
            "cases": [
                {"id": r.id, "passed": r.passed, "metrics": r.metrics, "observed": r.observed}
                for r in self.results
            ],
        }


class EvalSuite:
    def __init__(self, analyzer: Optional[TaskAnalyzer] = None,
                 graph: Optional[CapabilityGraph] = None, root=None,
                 memory=None):
        """`memory=None` is the static baseline; pass a MemoryAdvisor to score
        AMMO's decisions WITH accumulated experience (learning mode)."""
        self.analyzer = analyzer or TaskAnalyzer(systems=[])
        self.graph = graph or CapabilityGraph.from_registry(root)
        self.memory = memory
        self._root = root

    def _workflows_for(self, task):
        """Mirror the CLI: the candidate pack's workflows can route the team."""
        system_id = task.candidate_systems[0] if task.candidate_systems else None
        if not system_id or self._root is None:
            return None
        try:
            from ammo.registry import SystemPackLoader

            return SystemPackLoader(self._root).load(system_id).workflow_list
        except Exception:
            return None

    def run(self, cases: List[EvalCase]) -> SuiteReport:
        return SuiteReport([self.run_case(c) for c in cases])

    def run_case(self, case: EvalCase) -> CaseResult:
        task = self.analyzer.analyze(case.input)
        plan = TeamFormer(self.graph, memory=self.memory,
                          workflows=self._workflows_for(task)).form(task)
        result = Runner(lambda model_id: MockAdapter(model_id)).run(plan, task)
        report = ConfidenceEngine().assess(task, plan, result.responses, mode=result.mode)

        expect = case.expect
        band = report.confidence_band
        max_band = expect.get("confidence_max", "medium")

        metrics = {
            "selected_system_correct": plan.selected_system == expect.get("system"),
            "selected_team_correct": set(plan.roles) == set(expect.get("roles", [])),
            "confidence_reasonable": (
                band in _BAND_ORDER and _BAND_ORDER[band] <= _BAND_ORDER.get(max_band, 2)
            ),
            "required_tools_detected": set(expect.get("tools", [])).issubset(set(plan.required_tools)),
            "policy_decision_correct": report.required_next_action == expect.get("policy", DEFAULT_POLICY),
        }
        observed = {
            "system": plan.selected_system,
            "roles": plan.roles,
            "tools": plan.required_tools,
            "confidence_band": band,
            "confidence_score": report.confidence_score,
            "next_action": report.required_next_action,
        }
        return CaseResult(case.id, metrics, observed)
