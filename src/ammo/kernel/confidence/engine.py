"""Confidence Engine v0 — evidence-based, not model-self-confidence.

AMMO's differentiator: trust is *computed* from what actually happened (evidence
produced, independent critic outcome, model agreement, unresolved objections,
risk, missing evidence, real-vs-mock execution) — NOT from any model claiming to
be confident. This engine deliberately never reads ``AdapterResponse.confidence``.
"""

from __future__ import annotations

from typing import Iterable, List, Optional

from ammo.adapters.contract import AdapterResponse
from ammo.kernel.confidence.confidence_report import ConfidenceReport
from ammo.kernel.task_understanding.task_vector import TaskVector
from ammo.kernel.team_formation.execution_plan import ExecutionPlan

_CHECKER_ROLES = {"critic", "skeptic", "judge", "reviewer", "rollback_critic"}
_BUILDER_ROLES = {"builder", "operator"}
_REAL_TEST_KINDS = {"test_result", "tests"}
_TOOL_EXEC_KINDS = {"fs_write", "shell", "file_read"}  # ToolExecutor evidence

_BASE = 0.5


def _band(score: float) -> str:
    if score >= 0.75:
        return "high"
    if score >= 0.5:
        return "medium"
    if score >= 0.25:
        return "low"
    return "very_low"


class ConfidenceEngine:
    def assess(
        self,
        task: TaskVector,
        plan: ExecutionPlan,
        responses: List[AdapterResponse],
        *,
        objections: Optional[Iterable[str]] = None,
        risk: Optional[str] = None,
        mode: str = "mock",
        verification: Optional[dict] = None,
    ) -> ConfidenceReport:
        risk = risk or task.risk
        score = _BASE
        pos: List[str] = []
        neg: List[str] = []

        team_size = len(plan.selected_team)
        checker_roles_present = sorted({r.role for r in responses} & _CHECKER_ROLES)
        all_evidence = [ev for r in responses for ev in r.evidence]

        # objections: explicit ones + any checker evidence that did NOT pass
        open_objections: List[str] = list(objections or [])
        for r in responses:
            if r.role in _CHECKER_ROLES:
                for ev in r.evidence:
                    if not ev.ok:
                        open_objections.append(f"{r.role}: {ev.summary}")

        # 1. required workflow completed
        if responses and len(responses) == team_size and all(r.output for r in responses):
            score += 0.10
            pos.append("required workflow completed")
        else:
            score -= 0.10
            neg.append("workflow incomplete")

        # 2. independent critic pass
        if checker_roles_present and not open_objections:
            score += 0.12
            pos.append(f"independent {checker_roles_present[0]} passed")

        # 3. model agreement (distinct models, a checker in the loop, no objections)
        distinct_models = {r.model for r in responses}
        if len(distinct_models) >= 2 and checker_roles_present and not open_objections:
            score += 0.10
            pos.append("producer and checker agreed")

        # 4. tests: real passing test evidence raises; a code change without it lowers
        tests_passed = any(ev.kind in _REAL_TEST_KINDS and ev.ok for ev in all_evidence)
        code_change = task.domain == "coding" and any(r.role in _BUILDER_ROLES for r in responses)
        if tests_passed:
            score += 0.15
            pos.append("tests passed")
        elif code_change or task.needs_tests:
            score -= 0.08
            neg.append("no real tests executed")

        # 5. unresolved objections lower confidence
        if open_objections:
            score -= min(len(open_objections), 3) * 0.12
            for obj in open_objections[:3]:
                neg.append(f"unresolved objection — {obj}")

        # 5b. verification.yaml: the system declares what counts as success here
        declared = list((verification or {}).get("success_evidence") or [])[:3]
        for kind in declared:
            if any(ev.kind == kind and ev.ok for ev in all_evidence):
                score += 0.06
                pos.append(f"declared success evidence present: {kind}")
            else:
                score -= 0.06
                neg.append(f"declared success evidence missing: {kind}")

        # 5c. verification.yaml required_outputs: a complete result here must
        # plan for these outputs — an unplanned one is a completeness gap
        required = list((verification or {}).get("required_outputs") or [])[:3]
        planned = {o.lower() for o in (plan.expected_outputs or [])}
        for output in required:
            if str(output).lower() not in planned:
                score -= 0.05
                neg.append(f"declared required output not planned: {output}")

        # 6. tool outcomes: a denied tool means a member wanted a capability it
        # never got; a failed execution means claimed work didn't happen. Both
        # make the output less trustworthy. Successful side-effecting execution
        # is real evidence and raises trust slightly.
        tool_denials = [ev for ev in all_evidence if ev.kind == "tool" and not ev.ok]
        tool_failures = [ev for ev in all_evidence
                         if ev.kind in _TOOL_EXEC_KINDS and not ev.ok]
        for ev in tool_denials[:2]:
            score -= 0.06
            neg.append(f"tool denied — {ev.summary}")
        if len(tool_denials) > 2:
            neg.append(f"(+{len(tool_denials) - 2} more tool denial(s))")
        for ev in tool_failures[:2]:
            score -= 0.06
            neg.append(f"tool failed — {ev.summary}")
        if len(tool_failures) > 2:
            neg.append(f"(+{len(tool_failures) - 2} more tool failure(s))")
        if not tool_failures and any(
            ev.kind in {"fs_write", "shell"} and ev.ok for ev in all_evidence
        ):
            score += 0.05
            pos.append("side-effecting tools executed successfully")

        # 7. risk
        if risk == "high":
            score -= 0.15
            neg.append("high-risk task lowers confidence")
        elif risk == "medium":
            score -= 0.05
            neg.append("medium-risk task")

        # 8. missing evidence
        if not all_evidence:
            score -= 0.10
            neg.append("no evidence produced")
        elif mode == "real":
            # real mode is only trustworthy when members back their work:
            # a majority of evidence-free members caps the optimism
            no_evidence = [r for r in responses if not r.evidence]
            if responses and len(no_evidence) * 2 > len(responses):
                score -= 0.06
                neg.append("most members produced no structured evidence")

        # 9. mock execution (no real work happened)
        if mode == "mock":
            score -= 0.08
            neg.append("mock adapter only; no real execution")

        score = round(min(1.0, max(0.0, score)), 2)
        return ConfidenceReport(
            confidence_score=score,
            confidence_band=_band(score),
            reasons_positive=pos,
            reasons_negative=neg,
            required_next_action=self._next_action(
                mode, open_objections, risk, score,
                tool_issues=len(tool_denials) + len(tool_failures),
            ),
        )

    def _next_action(self, mode: str, objections: List[str], risk: str, score: float,
                     tool_issues: int = 0) -> str:
        if mode == "mock":
            return "require real execution before applying changes"
        if objections:
            return f"resolve {len(objections)} open objection(s) before proceeding"
        if tool_issues:
            return (f"resolve {tool_issues} tool denial(s)/failure(s) — grant the "
                    "permission, fix the tool call, or re-plan without it")
        if risk == "high" and score < 0.75:
            return "add an independent critic and re-run before applying"
        if score < 0.5:
            return "escalate: re-form the team or gather more evidence"
        return "proceed"
