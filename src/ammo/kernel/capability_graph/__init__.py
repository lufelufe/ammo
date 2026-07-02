"""Capability Graph (v0).

Loads model nodes from ``registry/models.yaml`` and scores them against a
TaskVector so AMMO can eventually pick models by capability, not by name. No
model is executed and no team is formed here.
"""

from ammo.kernel.capability_graph.graph import CapabilityGraph
from ammo.kernel.capability_graph.model_node import ModelNode
from ammo.kernel.capability_graph.scoring import (
    ScoredModel,
    score_model,
    score_models,
    task_needs,
)

__all__ = [
    "CapabilityGraph",
    "ModelNode",
    "ScoredModel",
    "score_model",
    "score_models",
    "task_needs",
]
