"""System-level evaluation (Phase-adjacent).

Judges whether a whole system is set up well and performing — works /
improvements / problems / health — from contract, capability coverage, spec
completeness, and run history. Read-only.
"""

from ammo.kernel.evaluation.engine import EvaluationEngine
from ammo.kernel.evaluation.report import EvaluationReport

__all__ = ["EvaluationEngine", "EvaluationReport"]
