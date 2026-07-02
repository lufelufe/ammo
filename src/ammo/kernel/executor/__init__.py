"""Execution subsystem (conceptual Phase 5) + run logging (Milestone 8).

Converts an ExecutionPlan into an ordered ExecutionGraph, runs it sequentially
through model adapters, and persists every run under ``runtime/runs/<run_id>/``.
With MockAdapter it is deterministic and offline — no real model is called.
"""

from ammo.kernel.executor.execution_graph import ExecutionGraph, ExecutionStep
from ammo.kernel.executor.result import ExecutionResult
from ammo.kernel.executor.run_store import RUN_FILES, RunStore
from ammo.kernel.executor.runner import Runner

__all__ = [
    "ExecutionGraph",
    "ExecutionStep",
    "ExecutionResult",
    "Runner",
    "RunStore",
    "RUN_FILES",
]
