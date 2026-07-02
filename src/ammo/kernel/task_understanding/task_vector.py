"""The TaskVector — AMMO's structured understanding of a request.

AMMO does not reduce a request to a single label ("coding"). It captures the
dimensions that actually drive team formation: domain, intent, risk, tools,
candidate systems, complexity, privacy, and a set of boolean needs. This module
defines only the data structure; classification lives in ``analyzer.py``.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List

# Canonical vocabularies (documented here as the contract for v0).
DOMAINS = ("personal", "research", "investment", "coding", "ops", "writing", "general")
LEVELS = ("low", "medium", "high")
CONTEXT_SIZES = ("small", "medium", "large")
PRIVACY_LEVELS = ("public", "personal", "private")


@dataclass
class TaskVector:
    """A rule-derived, model-free understanding of one request."""

    raw_input: str
    domain: str = "general"
    intent: str = "answer"
    complexity: str = "low"          # low | medium | high
    risk: str = "low"                # low | medium | high
    context_size: str = "small"      # small | medium | large
    required_tools: List[str] = field(default_factory=list)
    candidate_systems: List[str] = field(default_factory=list)
    output_type: str = "answer"
    privacy_level: str = "public"    # public | personal | private
    needs_current_info: bool = False
    needs_code_execution: bool = False
    needs_tests: bool = False
    tags: List[str] = field(default_factory=list)
    understanding_source: str = "rules"

    def to_dict(self) -> Dict[str, Any]:
        """Ordered dict (field declaration order) suitable for JSON output."""
        return asdict(self)
