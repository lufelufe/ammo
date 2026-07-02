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

    def run(self, plan: ExecutionPlan, task: TaskVector) -> ExecutionResult:
        graph = ExecutionGraph.from_plan(plan)
        responses: List[AdapterResponse] = []
        context: Dict[str, str] = {}

        for step in graph.steps:
            adapter = self._make_adapter(step.model)
            request = AdapterRequest(
                role=step.role,
                model=step.model,
                task_input=task.raw_input,
                system=plan.selected_system,
                allowed_tools=list(plan.required_tools),
                context=dict(context),
            )
            response = adapter.execute(request)
            responses.append(response)
            context[step.role] = response.output

        return ExecutionResult(plan=plan, task=task, responses=responses, mode=self.mode)
