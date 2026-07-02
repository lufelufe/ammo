"""The ConfidenceReport — AMMO's evidence-based trust judgment for a run."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List


@dataclass
class ConfidenceReport:
    confidence_score: float           # 0.0 .. 1.0
    confidence_band: str              # very_low | low | medium | high
    reasons_positive: List[str] = field(default_factory=list)
    reasons_negative: List[str] = field(default_factory=list)
    required_next_action: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "confidence_score": self.confidence_score,
            "confidence_band": self.confidence_band,
            "reasons_positive": self.reasons_positive,
            "reasons_negative": self.reasons_negative,
            "required_next_action": self.required_next_action,
        }

    def to_card(self) -> str:
        lines = [f"Confidence: {self.confidence_score}", f"Band: {self.confidence_band}", "Positive:"]
        lines += [f"- {r}" for r in (self.reasons_positive or ["(none)"])]
        lines.append("Negative:")
        lines += [f"- {r}" for r in (self.reasons_negative or ["(none)"])]
        lines.append("Next action:")
        lines.append(f"- {self.required_next_action}")
        return "\n".join(lines)
