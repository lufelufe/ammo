"""Memory dream — automated consolidation of AMMO's quantitative memory.

Implements docs/MEMORY_DREAM.md for the SQLite aggregates, run artifacts, and
role journals. Dry-run by default; apply backs up the DB first.
"""

from ammo.dream.engine import DreamEngine, DreamReport

__all__ = ["DreamEngine", "DreamReport"]
