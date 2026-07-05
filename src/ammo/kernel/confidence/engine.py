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
    def __init__(self, calibration_offset: float = 0.0):
        # learned correction from `ammo calibrate --apply` (user verdicts vs
        # scores). Bounded at the source (calibration.OFFSET_CAP); clamped
        # here too so a hand-edited config can't inject a wild swing.
        self._offset = max(-0.15, min(0.15, float(calibration_offset or 0.0)))

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

        # objections: explicit ones + any checker evidence that did NOT pass.
        # kind='challenge' is a DEBATE opening move (process, not verdict) and
        # is deliberately excluded — only the final review counts.
        open_objections: List[str] = list(objections or [])
        for r in responses:
            if r.role in _CHECKER_ROLES:
                for ev in r.evidence:
                    if not ev.ok and ev.kind != "challenge":
                        open_objections.append(f"{r.role}: {ev.summary}")

        # 1. required workflow completed — every planned SEAT produced output
        # (debate/consensus add extra responses per seat, so count roles, not rows)
        planned_roles = {m.role for m in plan.selected_team}
        covered_roles = {r.role for r in responses if r.output}
        if responses and planned_roles <= covered_roles:
            score += 0.10
            pos.append("required workflow completed")
        else:
            score -= 0.10
            neg.append("workflow incomplete")

        # 2. independent critic pass
        if checker_roles_present and not open_objections:
            score += 0.12
            pos.append(f"independent {checker_roles_present[0]} passed")

        # 3. agreement — MEASURED consensus when sampled (a checker compared
        # independent answers), else the distinct-models proxy
        consensus_evidence = [ev for ev in all_evidence if ev.kind == "consensus"]
        if consensus_evidence:
            final_consensus = consensus_evidence[-1]
            if final_consensus.ok:
                score += 0.10
                pos.append("measured consensus: independent models agree")
            else:
                score -= 0.08
                neg.append(f"measured consensus failed — {final_consensus.summary}")
        else:
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

        # 5a2. debate: an opening objection later resolved (final review PASS)
        # is stronger evidence than never having been challenged at all
        had_challenge = any(ev.kind == "challenge" and not ev.ok
                            for ev in all_evidence)
        final_reviews = [ev for r in responses if r.role in _CHECKER_ROLES
                         for ev in r.evidence if ev.kind == "review"]
        if had_challenge and final_reviews and final_reviews[-1].ok:
            score += 0.05
            pos.append("objection resolved through debate")

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

        # 9b. learned calibration: the user's verdicts said scores run
        # systematically high/low — shift toward ground truth. Applied BEFORE
        # the verification cap so a positive correction can never lift an
        # unverified real run into 'high'.
        if self._offset:
            score += self._offset
            note = (f"calibration correction {self._offset:+.2f} "
                    "(learned from user verdicts)")
            (pos if self._offset > 0 else neg).append(note)

        # 10. verification cap (real mode): a critic's pass and model agreement
        # are still model JUDGMENT. Without at least one MEASURED verification
        # signal — passing tests, measured consensus, a successful
        # side-effecting tool execution, declared success evidence, or an
        # objection resolved through adversarial debate — a real run cannot
        # claim the 'high' band, however smooth it looked.
        capped_unverified = False
        if mode == "real":
            declared_present = any(
                any(ev.kind == kind and ev.ok for ev in all_evidence)
                for kind in declared
            )
            verified = (
                tests_passed
                or any(ev.kind == "consensus" and ev.ok for ev in all_evidence)
                or any(ev.kind in {"fs_write", "shell"} and ev.ok
                       for ev in all_evidence)
                or declared_present
                or (had_challenge and final_reviews and final_reviews[-1].ok)
            )
            if not verified and score >= 0.75:
                score = 0.74
                capped_unverified = True
                neg.append("no measured verification (tests/consensus/tools) "
                           "— capped below 'high'")

        score = round(min(1.0, max(0.0, score)), 2)
        return ConfidenceReport(
            confidence_score=score,
            confidence_band=_band(score),
            reasons_positive=pos,
            reasons_negative=neg,
            required_next_action=self._next_action(
                mode, open_objections, risk, score,
                tool_issues=len(tool_denials) + len(tool_failures),
                capped_unverified=capped_unverified,
            ),
        )

    def _next_action(self, mode: str, objections: List[str], risk: str, score: float,
                     tool_issues: int = 0, capped_unverified: bool = False) -> str:
        if mode == "mock":
            return "require real execution before applying changes"
        if objections:
            return f"resolve {len(objections)} open objection(s) before proceeding"
        if tool_issues:
            return (f"resolve {tool_issues} tool denial(s)/failure(s) — grant the "
                    "permission, fix the tool call, or re-plan without it")
        if capped_unverified:
            return ("add measured verification (run tests, --consensus N, or "
                    "--execute-tools) to earn 'high' confidence")
        if risk == "high" and score < 0.75:
            return "add an independent critic and re-run before applying"
        if score < 0.5:
            return "escalate: re-form the team or gather more evidence"
        return "proceed"
