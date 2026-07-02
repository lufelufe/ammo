"""Score capability-graph nodes against a TaskVector.

This is *selection preparation*, not team formation: it ranks how well each model
fits a task, with explainable reasons. Team formation (Phase 4) will consume this
ranking; here we only produce it. No model is called.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Set, Tuple

from ammo.kernel.capability_graph.graph import CapabilityGraph
from ammo.kernel.capability_graph.model_node import ModelNode
from ammo.kernel.task_understanding.task_vector import TaskVector

# domain -> capabilities the task needs
DOMAIN_CAPABILITY = {
    "coding": ["coding"],
    "research": ["research", "analysis"],
    "investment": ["research", "analysis"],
    "personal": ["planning", "general"],
    "ops": ["ops", "general"],
    "writing": ["writing"],
    "general": ["general"],
}

# intent -> the PRIMARY roles the task needs
INTENT_ROLE = {
    "debug_and_patch": ["implementer"],
    "implement": ["implementer"],
    "refactor": ["implementer"],
    "coding_task": ["implementer"],
    "code_review": ["reviewer", "critic"],
    "explain": ["analyst"],
    "verify": ["critic", "reviewer"],
    "literature_scan": ["analyst"],
    "synthesize": ["synthesizer"],
    "research_investigation": ["analyst"],
    "investment_intel": ["analyst", "synthesizer"],
    "schedule": ["analyst"],
    "deploy": ["analyst"],
    "monitor": ["analyst"],
    "ops_task": ["analyst"],
    "briefing": ["synthesizer", "analyst"],
    "personal_task": ["synthesizer"],
    "compose": ["synthesizer"],
    "answer": ["synthesizer"],
}

# scoring weights
_W_CAPABILITY = 3
_W_PRIMARY_ROLE = 3
_W_SECONDARY_ROLE = 1
_WIDE_CONTEXT = 100_000
_NARROW_CONTEXT = 32_000


@dataclass
class ScoredModel:
    model_id: str
    score: int
    reasons: List[str] = field(default_factory=list)
    node: ModelNode = None

    def to_dict(self):
        return {"model_id": self.model_id, "score": self.score, "reasons": self.reasons}


def task_needs(task: TaskVector) -> Tuple[Set[str], Set[str], Set[str]]:
    """Return (primary_roles, secondary_roles, needed_capabilities) for a task."""
    caps = set(DOMAIN_CAPABILITY.get(task.domain, ["general"]))
    if task.needs_code_execution:
        caps.add("coding")

    primary_roles = set(INTENT_ROLE.get(task.intent, []))
    secondary_roles: Set[str] = set()
    if task.needs_tests:
        secondary_roles.update({"reviewer", "critic"})
    secondary_roles -= primary_roles  # don't double-count
    return primary_roles, secondary_roles, caps


def score_model(task: TaskVector, node: ModelNode) -> ScoredModel:
    primary_roles, secondary_roles, needed_caps = task_needs(task)
    score = 0
    reasons: List[str] = []

    for cap in sorted(needed_caps & set(node.capabilities)):
        score += _W_CAPABILITY
        reasons.append(f"capability:{cap}")
    for role in sorted(primary_roles & set(node.roles)):
        score += _W_PRIMARY_ROLE
        reasons.append(f"role:{role}")
    for role in sorted(secondary_roles & set(node.roles)):
        score += _W_SECONDARY_ROLE
        reasons.append(f"role+:{role}")

    if task.context_size == "large":
        if node.context_window >= _WIDE_CONTEXT:
            score += 1
            reasons.append("wide-context")
        elif node.context_window and node.context_window < _NARROW_CONTEXT:
            score -= 1
            reasons.append("narrow-context")

    if task.risk == "high" and node.cost_class == "premium":
        score += 1
        reasons.append("premium-for-high-risk")
    if task.risk == "low" and node.cost_class == "cheap":
        score += 1
        reasons.append("cheap-for-low-risk")
    if task.complexity == "low" and node.latency_class == "fast":
        score += 1
        reasons.append("fast")
    if node.warm_status == "warm":
        score += 1
        reasons.append("warm")

    return ScoredModel(model_id=node.id, score=score, reasons=reasons, node=node)


def score_models(task: TaskVector, graph: CapabilityGraph) -> List[ScoredModel]:
    """Rank enabled nodes best-first (ties broken by id for determinism)."""
    scored = [score_model(task, node) for node in graph.enabled()]
    scored.sort(key=lambda s: (-s.score, s.model_id))
    return scored
