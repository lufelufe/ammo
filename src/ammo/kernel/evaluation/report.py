"""The EvaluationReport — a system-level health judgment.

Distinct from a single run's ConfidenceReport: this asks whether an entire system
is set up well and performing over time — what works, what to improve, and what
is broken.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List


@dataclass
class EvaluationReport:
    system: str
    health: str                       # healthy | ok | unproven | at_risk
    works: List[str] = field(default_factory=list)
    improvements: List[str] = field(default_factory=list)
    problems: List[str] = field(default_factory=list)
    stats: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "system": self.system,
            "health": self.health,
            "works": self.works,
            "improvements": self.improvements,
            "problems": self.problems,
            "stats": self.stats,
        }

    def to_card(self) -> str:
        lines = [f"System: {self.system}", f"Health: {self.health}", "Works:"]
        lines += [f"- {r}" for r in (self.works or ["(none)"])]
        lines.append("Improvements:")
        lines += [f"- {r}" for r in (self.improvements or ["(none)"])]
        lines.append("Problems:")
        lines += [f"- {r}" for r in (self.problems or ["(none)"])]
        return "\n".join(lines)
