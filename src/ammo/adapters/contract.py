"""The Model Adapter contract.

AMMO never talks to a model directly — it talks to a ``BaseModelAdapter``. This
module defines the vendor-neutral request/response types and the abstract
adapter interface. Real adapters (Claude, Codex, local) and the MockAdapter all
implement the same contract, so the kernel stays model-agnostic.
"""

from __future__ import annotations

import abc
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class ToolRequest:
    """A worker's *declared* intent to use a tool (declared, not executed here)."""

    tool: str
    args: Dict[str, Any] = field(default_factory=dict)
    reason: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class Evidence:
    """A verifiable artifact a worker produced (seeds the Confidence Engine)."""

    kind: str            # e.g. "diff", "test_result", "citation", "review"
    summary: str
    ok: bool = True
    detail: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class Usage:
    """Token usage for one adapter call (estimated when the CLI reports none)."""

    input_tokens: int = 0
    output_tokens: int = 0
    estimated: bool = True
    cost_usd: Optional[float] = None   # real cost when the provider reports it

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class AdapterRequest:
    """What AMMO sends to an adapter for one team member's turn."""

    role: str                       # team position, e.g. "planner"
    model: str                      # model id the plan assigned
    task_input: str                 # the user's raw request
    system: Optional[str] = None    # selected system pack id
    allowed_tools: List[str] = field(default_factory=list)
    context: Dict[str, str] = field(default_factory=dict)  # prior role -> output

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class AdapterResponse:
    """What an adapter returns for one team member's turn."""

    role: str
    model: str
    output: str
    confidence: float = 0.0
    reasoning: str = ""
    tool_requests: List[ToolRequest] = field(default_factory=list)
    evidence: List[Evidence] = field(default_factory=list)
    usage: Optional[Usage] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "role": self.role,
            "model": self.model,
            "output": self.output,
            "confidence": self.confidence,
            "reasoning": self.reasoning,
            "tool_requests": [t.to_dict() for t in self.tool_requests],
            "evidence": [e.to_dict() for e in self.evidence],
            "usage": self.usage.to_dict() if self.usage else None,
        }


class BaseModelAdapter(abc.ABC):
    """The single interface AMMO depends on. No vendor specifics leak above this."""

    def __init__(self, model_id: str):
        self.model_id = model_id

    @abc.abstractmethod
    def describe(self) -> Dict[str, Any]:
        """Static, cheap description of this adapter (no network)."""

    @abc.abstractmethod
    def execute(self, request: AdapterRequest) -> AdapterResponse:
        """Run one unit of work for a team member. May be mock or real."""
