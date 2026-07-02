"""AMMO eval suite — measure whether AMMO's decisions are improving.

Runs sample tasks through the kernel (static, mock) and scores five metrics:
selected_system_correct, selected_team_correct, confidence_reasonable,
required_tools_detected, policy_decision_correct. This is the signal that makes
AMMO a *learning* router rather than a fixed one.
"""

from ammo.evalsuite.case import EvalCase, load_cases
from ammo.evalsuite.runner import METRICS, CaseResult, EvalSuite, SuiteReport

__all__ = ["EvalCase", "load_cases", "EvalSuite", "SuiteReport", "CaseResult", "METRICS"]
