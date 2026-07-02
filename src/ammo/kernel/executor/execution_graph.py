"""Execution graph — an ExecutionPlan turned into ordered execution steps.

v0 is a linear (sequential) chain: each team member becomes one ordered step.
Later versions may add fan-out/dependencies; the shape is kept explicit so that
can grow without changing callers.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List

from ammo.kernel.team_formation.execution_plan import ExecutionPlan


@dataclass
class ExecutionStep:
    order: int
    role: str
    model: str

    def to_dict(self) -> Dict[str, Any]:
        return {"order": self.order, "role": self.role, "model": self.model}


@dataclass
class ExecutionGraph:
    steps: List[ExecutionStep]

    @classmethod
    def from_plan(cls, plan: ExecutionPlan) -> "ExecutionGraph":
        return cls(
            [
                ExecutionStep(order=i, role=member.role, model=member.model)
                for i, member in enumerate(plan.selected_team)
            ]
        )

    def to_dict(self) -> Dict[str, Any]:
        return {"steps": [s.to_dict() for s in self.steps]}
