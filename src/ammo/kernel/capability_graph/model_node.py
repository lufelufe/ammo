"""A model node in the Capability Graph.

Each node is a *capability declaration* for one model adapter — what roles it can
play, what it is good at, and its cost/latency/context/warmth profile. Models are
plugins; the kernel reasons over these nodes instead of hard-coding model names.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List


@dataclass
class ModelNode:
    id: str
    provider: str = ""
    adapter: str = ""
    roles: List[str] = field(default_factory=list)
    capabilities: List[str] = field(default_factory=list)
    context_window: int = 0
    cost_class: str = "standard"     # cheap | standard | premium
    latency_class: str = "medium"    # fast | medium | slow
    warm_status: str = "cold"        # warm | cold
    enabled: bool = True

    @classmethod
    def from_dict(cls, entry: Dict[str, Any]) -> "ModelNode":
        return cls(
            id=entry["id"],
            provider=entry.get("provider", ""),
            adapter=entry.get("adapter", ""),
            roles=list(entry.get("roles") or []),
            capabilities=list(entry.get("capabilities") or []),
            context_window=int(entry.get("context_window") or 0),
            cost_class=entry.get("cost_class", "standard"),
            latency_class=entry.get("latency_class", "medium"),
            warm_status=entry.get("warm_status", "cold"),
            enabled=bool(entry.get("enabled", True)),
        )

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
