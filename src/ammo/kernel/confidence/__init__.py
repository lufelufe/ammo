"""Confidence Engine (v0, conceptual Phase 6).

Computes an evidence-based confidence score for a run — AMMO's differentiator.
It never trusts a model's self-reported confidence; it reasons over evidence,
independent critique, agreement, objections, risk, and real-vs-mock execution.
"""

from ammo.kernel.confidence.calibration import Calibration, calibrate
from ammo.kernel.confidence.confidence_report import ConfidenceReport
from ammo.kernel.confidence.engine import ConfidenceEngine

__all__ = ["Calibration", "ConfidenceEngine", "ConfidenceReport", "calibrate"]
