"""Model adapters — the boundary between AMMO and any model.

AMMO depends only on ``BaseModelAdapter`` and the vendor-neutral request/response
types. ``MockAdapter`` is a deterministic, offline implementation. Real Claude /
Codex / local adapters (Phase 9) will implement the same contract.
"""

from ammo.adapters.command_adapter import CommandAdapter
from ammo.adapters.resolver import RealAdapterFactory
from ammo.adapters.contract import (
    AdapterRequest,
    AdapterResponse,
    BaseModelAdapter,
    Evidence,
    ToolRequest,
    Usage,
)
from ammo.adapters.mock_adapter import MockAdapter

__all__ = [
    "AdapterRequest",
    "AdapterResponse",
    "BaseModelAdapter",
    "Evidence",
    "ToolRequest",
    "Usage",
    "MockAdapter",
    "CommandAdapter",
    "RealAdapterFactory",
]
