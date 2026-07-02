"""The structured result of an execution run.

Bundles the plan, per-member responses, the final deliverable, and a
*provisional* aggregate confidence (a plain mean of workers' self-reported
values — the real Confidence Engine is Phase 6). ``mode`` records whether real
or mock adapters ran.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List

from ammo.adapters.contract import AdapterResponse
from ammo.kernel.task_understanding.task_vector import TaskVector
from ammo.kernel.team_formation.execution_plan import ExecutionPlan


@dataclass
class ExecutionResult:
    plan: ExecutionPlan
    task: TaskVector
    responses: List[AdapterResponse]
    mode: str = "mock"

    @property
    def final_output(self) -> str:
        return self.responses[-1].output if self.responses else ""

    @property
    def self_reported_mean(self) -> float:
        """Mean of the models' SELF-reported confidences — informational only;
        the trusted score is the evidence-based ConfidenceEngine report."""
        if not self.responses:
            return 0.0
        return round(sum(r.confidence for r in self.responses) / len(self.responses), 3)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "task": self.task.raw_input,
            "mode": self.mode,
            "selected_system": self.plan.selected_system,
            "team": [m.to_dict() for m in self.plan.selected_team],
            "steps": [r.to_dict() for r in self.responses],
            "risk_controls": self.plan.risk_controls,
            "expected_outputs": self.plan.expected_outputs,
            "final_output": self.final_output,
            "self_reported_mean": self.self_reported_mean,
        }
