"""The ExecutionPlan — AMMO's temporary team for one task.

This is the output of team formation: which system serves the task, which
(role, model) members make up the team, the tools they may use, the risk
controls that bound them, and the outputs expected. It is a *plan* — nothing is
executed here.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class TeamMember:
    role: str          # team position, e.g. "planner", "builder", "critic"
    model: str         # capability-graph model id, or a fixed infra id

    def to_dict(self) -> Dict[str, str]:
        return {"role": self.role, "model": self.model}


@dataclass
class ExecutionPlan:
    selected_system: Optional[str]
    selected_team: List[TeamMember] = field(default_factory=list)
    roles: List[str] = field(default_factory=list)
    reasoning_summary: str = ""
    required_tools: List[str] = field(default_factory=list)
    risk_controls: List[str] = field(default_factory=list)
    expected_outputs: List[str] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)  # e.g. memory-guided pick explanations
    workflow: Optional[str] = None          # pack workflow id when stage-routed
    workflow_gate: Optional[float] = None   # that workflow's confidence_gate
    debate: Optional[Dict[str, Any]] = None # {proposer, challenger, rounds}

    def to_dict(self) -> Dict[str, Any]:
        return {
            "selected_system": self.selected_system,
            "selected_team": [m.to_dict() for m in self.selected_team],
            "roles": self.roles,
            "reasoning_summary": self.reasoning_summary,
            "required_tools": self.required_tools,
            "risk_controls": self.risk_controls,
            "expected_outputs": self.expected_outputs,
            "notes": self.notes,
            "workflow": self.workflow,
            "workflow_gate": self.workflow_gate,
            "debate": self.debate,
        }
