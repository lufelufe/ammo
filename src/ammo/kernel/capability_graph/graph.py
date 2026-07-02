"""The Capability Graph — the set of model nodes AMMO can choose from.

Loads nodes from ``registry/models.yaml`` and offers capability/role queries.
No model is executed; this is pure selection substrate for later team formation.
"""

from __future__ import annotations

from pathlib import Path
from typing import List, Optional

from ammo.kernel.capability_graph.model_node import ModelNode


class CapabilityGraph:
    def __init__(self, nodes: List[ModelNode]):
        self.nodes = list(nodes)

    @classmethod
    def from_registry(cls, root: Optional[Path] = None) -> "CapabilityGraph":
        # Imported lazily so the graph module has no hard dependency at import.
        from ammo.paths import find_ammo_root
        from ammo.registry import load_models

        root = root if root is not None else find_ammo_root()
        return cls([ModelNode.from_dict(entry) for entry in load_models(root)])

    def enabled(self) -> List[ModelNode]:
        return [n for n in self.nodes if n.enabled]

    def by_role(self, role: str) -> List[ModelNode]:
        return [n for n in self.enabled() if role in n.roles]

    def by_capability(self, capability: str) -> List[ModelNode]:
        return [n for n in self.enabled() if capability in n.capabilities]

    def get(self, model_id: str) -> Optional[ModelNode]:
        for node in self.nodes:
            if node.id == model_id:
                return node
        return None
