"""Sequential runner — execute an ExecutionGraph through model adapters.

Depends only on the adapter contract: it is handed a factory
``model_id -> BaseModelAdapter`` and never imports a concrete model. Each step
receives the prior steps' outputs as context. With MockAdapter this is fully
offline and deterministic.
"""

from __future__ import annotations

from typing import Callable, Dict, List

from ammo.adapters.contract import AdapterRequest, AdapterResponse, BaseModelAdapter
from ammo.kernel.executor.execution_graph import ExecutionGraph
from ammo.kernel.executor.result import ExecutionResult
from ammo.kernel.task_understanding.task_vector import TaskVector
from ammo.kernel.team_formation.execution_plan import ExecutionPlan

AdapterFactory = Callable[[str], BaseModelAdapter]


class Runner:
    def __init__(self, adapter_factory: AdapterFactory, mode: str = "mock"):
        self._make_adapter = adapter_factory
        self.mode = mode

    def run(self, plan: ExecutionPlan, task: TaskVector, *,
            system_context: str = "", role_context: Dict[str, str] = None) -> ExecutionResult:
        """`system_context` is the pack's context.md (operating guidance);
        `role_context` maps role -> that role's distilled memory (insights/last).
        Both are injected into every worker's request context."""
        graph = ExecutionGraph.from_plan(plan)
        responses: List[AdapterResponse] = []
        context: Dict[str, str] = {}
        role_context = role_context or {}

        for step in graph.steps:
            adapter = self._make_adapter(step.model)
            step_context = dict(context)
            if system_context:
                step_context["system_context"] = system_context[:2000]
            role_memory = role_context.get(step.role)
            if role_memory:
                step_context["role_memory"] = role_memory[:1000]
            request = AdapterRequest(
                role=step.role,
                model=step.model,
                task_input=task.raw_input,
                system=plan.selected_system,
                allowed_tools=list(plan.required_tools),
                context=step_context,
            )
            response = adapter.execute(request)
            responses.append(response)
            context[step.role] = response.output

        return ExecutionResult(plan=plan, task=task, responses=responses, mode=self.mode)
