"""Task Understanding (rule-based v0).

Turns a raw request into a structured :class:`TaskVector` — domain, intent,
risk, tools, candidate systems, and needs — without calling any model.
"""

from ammo.kernel.task_understanding.analyzer import (
    DOMAIN_TO_SYSTEMS,
    TaskAnalyzer,
    analyze,
)
from ammo.kernel.task_understanding.task_vector import TaskVector

__all__ = ["DOMAIN_TO_SYSTEMS", "TaskAnalyzer", "TaskVector", "analyze"]
