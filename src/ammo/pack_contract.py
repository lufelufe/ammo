"""System Pack contract (Milestone 1).

Single source of truth for the *structure* of an AMMO system pack. This module
contains **no execution or orchestration logic** — only the names of the files a
pack must declare and pure helpers to check a pack's structure on disk.

A system pack lives at ``systems/<id>/`` and declares a ``.ammo/`` meta layer
plus a human-readable ``system.md``. Each ``.ammo`` file maps to a stage of the
kernel loop (see docs/SYSTEM_PACK_SPEC.md):

    manifest.yaml     -> identity & declared capabilities
    routing.yaml      -> task understanding / routing
    memory_map.yaml   -> the learning-memory feedback loop
    permissions.yaml  -> the security boundary
    workflows.yaml    -> team shape + confidence gates (declarative)
"""

from __future__ import annotations

from pathlib import Path
from typing import List

# The meta directory declared inside every system pack.
AMMO_DIR = ".ammo"

# The five .ammo meta files every system pack must declare.
REQUIRED_AMMO_FILES = (
    "manifest.yaml",
    "routing.yaml",
    "memory_map.yaml",
    "permissions.yaml",
    "workflows.yaml",
)

# Files required at the pack root (outside .ammo/).
REQUIRED_ROOT_FILES = ("system.md",)

# System packs expected to exist as of Milestone 1.
EXPECTED_SYSTEMS = ("personal", "research", "coding", "ops")

# Top-level DATA directories the kernel governs (code dirs are separate).
REQUIRED_TOP_LEVEL_DIRS = ("systems", "registry", "memory", "runtime", "vaults")

# Registry files the kernel expects under registry/.
REQUIRED_REGISTRY_FILES = ("systems.yaml", "models.yaml", "tools.yaml", "roles.yaml")

# Data directories that must be writable at runtime.
WRITABLE_DIRS = ("runtime", "memory")

# Optional per-system OPTIMIZATION specs (absent = safe defaults; never required).
OPTIONAL_AMMO_FILES = ("preferences.yaml", "verification.yaml", "limits.yaml")
OPTIONAL_ROOT_FILES = ("context.md",)
IGNORE_FILE = ".ammoignore"


def pack_dir(systems_root: Path, system_id: str) -> Path:
    """Return the directory of a pack given the ``systems/`` root."""
    return Path(systems_root) / system_id


def required_paths(systems_root: Path, system_id: str) -> List[Path]:
    """Return every path a pack must contain to satisfy the contract."""
    base = pack_dir(systems_root, system_id)
    paths = [base / name for name in REQUIRED_ROOT_FILES]
    paths += [base / AMMO_DIR / name for name in REQUIRED_AMMO_FILES]
    return paths


def missing_pack_files(systems_root: Path, system_id: str) -> List[Path]:
    """Return the required paths that do not exist for a pack (empty = valid)."""
    return [p for p in required_paths(systems_root, system_id) if not p.exists()]


def discover_pack_ids(systems_root: Path) -> List[str]:
    """Return the ids of on-disk packs (dirs under systems/ that hold a .ammo/).

    Pure structural discovery — reads the filesystem only, never executes or
    parses pack contents.
    """
    root = Path(systems_root)
    if not root.is_dir():
        return []
    ids = []
    for child in sorted(root.iterdir()):
        if child.is_dir() and (child / AMMO_DIR).is_dir():
            ids.append(child.name)
    return ids
