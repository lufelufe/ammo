"""Sequential runner — execute an ExecutionGraph through model adapters.

Depends only on the adapter contract: it is handed a factory
``model_id -> BaseModelAdapter`` and never imports a concrete model. Each step
receives the prior steps' outputs as context. With MockAdapter this is fully
offline and deterministic.
"""

from __future__ import annotations

import re
from typing import Callable, Dict, List

from ammo.adapters.contract import AdapterRequest, AdapterResponse, BaseModelAdapter, Evidence
from ammo.kernel.confidence.engine import _CHECKER_ROLES as CHECKER_ROLES
from ammo.kernel.executor.execution_graph import ExecutionGraph
from ammo.kernel.executor.result import ExecutionResult
from ammo.kernel.task_understanding.task_vector import TaskVector
from ammo.kernel.team_formation.execution_plan import ExecutionPlan

AdapterFactory = Callable[[str], BaseModelAdapter]

# Real checkers must end with a machine-readable verdict so their pass/fail is
# EVIDENCE (parsed below), not vibes. Mock checkers already emit evidence.
VERDICT_INSTRUCTION = (
    "You are the team's checker. End your answer with exactly one final line: "
    "'VERDICT: PASS' if the prior members' work holds, or "
    "'VERDICT: FAIL — <short reason>' if it does not."
)
_VERDICT_RE = re.compile(r"VERDICT:\s*(PASS|FAIL)\b[\s—:–-]*(.*)", re.IGNORECASE)

REBUTTAL_INSTRUCTION = (
    "A challenger has objected to your earlier answer (see 'challenge' in the "
    "context). Defend it with evidence or REVISE it — output your final, "
    "corrected answer in full."
)
CONSENSUS_INSTRUCTION = (
    "Multiple models answered the lead question independently (see the "
    "'~alt' entries in the context). Compare them. Before your verdict, add "
    "exactly one line: 'CONSENSUS: agree' if they substantively agree, or "
    "'CONSENSUS: split — <the key difference>' if they do not."
)
_CONSENSUS_RE = re.compile(r"CONSENSUS:\s*(agree|split)\b[\s—:–-]*(.*)", re.IGNORECASE)

FINAL_VERDICT_INSTRUCTION = (
    "You are the team's checker in a debate. The proposer has responded to "
    "your challenge (see the context). Judge the FINAL state of the work. "
    "End with exactly one line: 'VERDICT: PASS' or 'VERDICT: FAIL — <reason>'."
)


def _parse_verdict(output: str):
    # scan lines bottom-up: the checker's FINAL verdict line wins, so an
    # earlier quote of the instruction text can't be mistaken for the verdict
    for line in reversed((output or "").splitlines()):
        match = _VERDICT_RE.search(line)
        if match:
            verdict, reason = match.groups()
            return verdict.upper() == "PASS", reason.strip().strip("'\"")
    return None


class Runner:
    def __init__(self, adapter_factory: AdapterFactory, mode: str = "mock",
                 max_retries: int = 1):
        self._make_adapter = adapter_factory
        self.mode = mode
        self.max_retries = max_retries

    def run(self, plan: ExecutionPlan, task: TaskVector, *,
            system_context: str = "", role_context: Dict[str, str] = None,
            grounding: str = "") -> ExecutionResult:
        """`system_context` is the pack's context.md (operating guidance);
        `role_context` maps role -> that role's distilled memory (insights/last);
        `grounding` is real file content read before the run (P1). All are
        injected into every worker's request context."""
        graph = ExecutionGraph.from_plan(plan)
        responses: List[AdapterResponse] = []
        context: Dict[str, str] = {}
        role_context = role_context or {}

        for step in graph.steps:
            adapter = self._make_adapter(step.model)
            step_context = dict(context)
            if system_context:
                step_context["system_context"] = system_context[:2000]
            if grounding:
                step_context["grounding"] = grounding
            role_memory = role_context.get(step.role)
            if role_memory:
                step_context["role_memory"] = role_memory[:1000]
            if step.role in CHECKER_ROLES:
                step_context["instruction"] = VERDICT_INSTRUCTION
                if plan.consensus:
                    step_context["instruction"] += "\n" + CONSENSUS_INSTRUCTION
            request = AdapterRequest(
                role=step.role,
                model=step.model,
                task_input=task.raw_input,
                system=plan.selected_system,
                allowed_tools=list(plan.required_tools),
                context=step_context,
            )
            response = self._execute_with_retry(adapter, request)
            self._attach_verdict_evidence(step.role, response)
            if step.role in CHECKER_ROLES and plan.consensus:
                self._attach_consensus_evidence(response)
            responses.append(response)
            context[step.role] = response.output

            # consensus: the lead seat's question is answered independently by
            # alternate models too; a later checker compares them (measured
            # agreement instead of the absence-of-objection proxy)
            consensus = plan.consensus
            if consensus and step.role == consensus["role"]:
                for alt_model in consensus.get("models") or []:
                    alt = self._execute_with_retry(
                        self._make_adapter(alt_model),
                        AdapterRequest(role=step.role, model=alt_model,
                                       task_input=task.raw_input,
                                       system=plan.selected_system,
                                       allowed_tools=list(plan.required_tools),
                                       context=dict(step_context)),
                    )
                    responses.append(alt)
                    context[f"{step.role}~alt:{alt_model}"] = alt.output

            # debate: the marked challenger's objection triggers rebuttal
            # rounds before the pipeline continues (challenge -> proposer
            # rebuttal -> challenger FINAL verdict; only the final one scores)
            debate = plan.debate
            if debate and step.role == debate["challenger"]:
                self._run_debate(plan, task, context, responses, debate,
                                 base_context={"system_context": step_context.get("system_context", "")})

        return ExecutionResult(plan=plan, task=task, responses=responses, mode=self.mode)

    def _run_debate(self, plan, task, context, responses, debate, base_context):
        models = {m.role: m.model for m in plan.selected_team}
        proposer, challenger = debate["proposer"], debate["challenger"]
        if proposer not in models or challenger not in models:
            return
        # the opening objection is part of the PROCESS, not the verdict:
        # downgrade its review evidence to 'challenge' so it isn't an objection
        for ev in responses[-1].evidence:
            if ev.kind == "review":
                ev.kind = "challenge"

        for _ in range(debate.get("rounds", 1)):
            rebuttal_ctx = dict(context)
            rebuttal_ctx.update(base_context)
            rebuttal_ctx["challenge"] = context.get(challenger, "")
            rebuttal_ctx["instruction"] = REBUTTAL_INSTRUCTION
            rebuttal = self._execute_with_retry(
                self._make_adapter(models[proposer]),
                AdapterRequest(role=proposer, model=models[proposer],
                               task_input=task.raw_input,
                               system=plan.selected_system,
                               allowed_tools=list(plan.required_tools),
                               context=rebuttal_ctx),
            )
            responses.append(rebuttal)
            context[proposer] = rebuttal.output

            final_ctx = dict(context)
            final_ctx.update(base_context)
            final_ctx["instruction"] = FINAL_VERDICT_INSTRUCTION
            final = self._execute_with_retry(
                self._make_adapter(models[challenger]),
                AdapterRequest(role=challenger, model=models[challenger],
                               task_input=task.raw_input,
                               system=plan.selected_system,
                               allowed_tools=list(plan.required_tools),
                               context=final_ctx),
            )
            # mock checkers re-emit review evidence; real ones emit a verdict
            self._attach_verdict_evidence(challenger, final)
            responses.append(final)
            context[challenger] = final.output

    def _execute_with_retry(self, adapter: BaseModelAdapter,
                            request: AdapterRequest) -> AdapterResponse:
        response = adapter.execute(request)
        attempts = 0
        while attempts < self.max_retries and self._failed(response):
            attempts += 1
            retried = adapter.execute(request)
            retried.evidence.append(Evidence(
                kind="invocation",
                summary=f"attempt {attempts} failed (empty/errored output); retried",
                ok=not self._failed(retried),
            ))
            response = retried
        return response

    @staticmethod
    def _failed(response: AdapterResponse) -> bool:
        text = (response.output or "").strip()
        return (not text or text.startswith("(command exited")
                or text.startswith("(api error"))

    @staticmethod
    def _attach_consensus_evidence(response: AdapterResponse) -> None:
        for line in reversed((response.output or "").splitlines()):
            match = _CONSENSUS_RE.search(line)
            if match:
                verdict, detail = match.groups()
                agree = verdict.lower() == "agree"
                response.evidence.append(Evidence(
                    kind="consensus",
                    summary="models agree" if agree
                    else f"models split — {detail.strip() or 'unspecified'}",
                    ok=agree, detail=detail.strip(),
                ))
                return

    @staticmethod
    def _attach_verdict_evidence(role: str, response: AdapterResponse) -> None:
        if role not in CHECKER_ROLES:
            return
        if any(ev.kind == "review" for ev in response.evidence):
            return  # adapter already produced structured review evidence (mock)
        verdict = _parse_verdict(response.output)
        if verdict is None:
            return
        passed, reason = verdict
        response.evidence.append(Evidence(
            kind="review",
            summary="checker verdict: PASS" if passed
            else f"checker verdict: FAIL — {reason or 'unspecified'}",
            ok=passed,
            detail=reason,
        ))
