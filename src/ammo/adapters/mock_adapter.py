"""MockAdapter — deterministic, offline role-based workers.

Produces stable, role-specific outputs with no randomness and no network, so the
whole analyze → form-team → execute pipeline can run and be tested without any
real model. Same request in → same response out.
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

from ammo.adapters.contract import (
    AdapterRequest,
    AdapterResponse,
    BaseModelAdapter,
    Evidence,
    ToolRequest,
    Usage,
)


def estimate_tokens(text: str) -> int:
    """Deterministic chars/4 token estimate (used when no real count exists)."""
    return max(1, len(text) // 4) if text else 0


class MockAdapter(BaseModelAdapter):
    def describe(self) -> Dict[str, Any]:
        return {"id": self.model_id, "kind": "mock", "deterministic": True}

    def execute(self, request: AdapterRequest) -> AdapterResponse:
        output, confidence, tools, evidence = self._role_work(request.role, request.task_input)
        prompt_text = request.task_input + "".join(request.context.values())
        return AdapterResponse(
            role=request.role,
            model=request.model,
            output=output,
            confidence=confidence,
            reasoning=f"mock:{request.role}",
            tool_requests=tools,
            evidence=evidence,
            usage=Usage(
                input_tokens=estimate_tokens(prompt_text),
                output_tokens=estimate_tokens(output),
                estimated=True,
            ),
        )

    # -- deterministic role behaviors ---------------------------------------

    def _role_work(
        self, role: str, task: str
    ) -> Tuple[str, float, List[ToolRequest], List[Evidence]]:
        n = len(task)  # stable, no randomness

        if role == "planner":
            return (
                f"Plan: 1) scope, 2) assign work, 3) verify — for: {task!r}",
                0.8,
                [],
                [Evidence("plan", "3-step plan produced")],
            )
        if role == "builder":
            return (
                f"Implemented a change addressing: {task!r}",
                0.75,
                [
                    ToolRequest("fs.write", {"target": "edited-files"}, "apply change"),
                    ToolRequest("git", {"op": "diff"}, "produce a reviewable diff"),
                ],
                [Evidence("diff", "code diff generated")],
            )
        if role == "critic":
            issues = n % 3
            return (
                f"Review complete: {issues} issue(s) flagged.",
                0.7,
                [],
                [Evidence("review", f"{issues} issue(s)", ok=(issues == 0))],
            )
        if role == "researcher":
            sources = 2 + n % 3
            return (
                f"Collected {sources} source(s) on: {task!r}",
                0.7,
                [ToolRequest("web.search", {"q": task}, "find sources")],
                [Evidence("sources", f"{sources} source(s) gathered")],
            )
        if role == "skeptic":
            return (
                "Challenged the strongest claim; 1 assumption needs support.",
                0.65,
                [],
                [Evidence("critique", "adversarial check performed")],
            )
        if role == "synthesizer":
            return (
                f"Synthesis: consolidated findings for: {task!r}",
                0.8,
                [],
                [Evidence("summary", "final synthesis produced")],
            )
        if role == "judge":
            return (
                "Verdict: acceptable, pending the listed risk controls.",
                0.8,
                [],
                [Evidence("verdict", "judged acceptable")],
            )
        if role == "fast_worker":
            return (
                f"Done: {task!r}",
                0.7,
                [],
                [Evidence("result", "single-pass result produced")],
            )

        # generic fallback for any other position (test_runner, operator, ...)
        return (
            f"[{role}] completed its step for: {task!r}",
            0.6,
            [],
            [Evidence(role, f"{role} step completed")],
        )
