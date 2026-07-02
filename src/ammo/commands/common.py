"""ammo CLI handlers — common (split from cli.py)."""

from pathlib import Path
from typing import Optional, Sequence
from ammo.binding import (
    BindingStore,
    available_choices,
    build_binding,
    existing_or_best,
)
from ammo.memory import MemoryAdvisor, MemoryStore, team_signature
from ammo.roles import RoleWorkspace
from ammo.registry import RegistryError, SystemPackLoader, enabled_systems


def _load_pack_for_task(root, task):
    """The candidate system's pack (specs: preferences/verification/limits/context)."""
    system_id = task.candidate_systems[0] if task.candidate_systems else None
    if not system_id:
        return None
    try:
        return SystemPackLoader(root).load(system_id)
    except RegistryError:
        return None


def _role_memory(root, system, roles):
    """Distilled per-role memory (insights.md + last.md) for read-back injection."""
    if not system:
        return {}
    workspace = RoleWorkspace(root)
    out = {}
    for role in roles:
        role_dir = workspace.path(system, role)
        parts = []
        for name in ("insights.md", "last.md"):
            f = role_dir / name
            if f.is_file():
                parts.append(f.read_text(encoding="utf-8")[-800:])
        if parts:
            out[role] = "\n".join(parts)
    return out


def _load_primary(root):
    """The summoning host's model from ammo.config.yaml (None if unset)."""
    from ammo.config import load_config

    config = load_config(root)
    return config.primary_model if config else None


def _resolve_objective(root, args) -> str:
    """CLI flag wins; else the configured default; else balanced."""
    flag = getattr(args, "optimize", None)
    if flag:
        return flag
    from ammo.config import load_config

    config = load_config(root)
    return config.default_objective if config else "balanced"


def _load_memory_advisor(root, args) -> Optional[MemoryAdvisor]:
    explore = float(getattr(args, "explore", 0.0) or 0.0)
    if getattr(args, "no_memory", False):
        return None
    # cold start: no memory db yet. Still allow exploration to try untried models.
    if not (Path(root) / "memory" / "ammo.sqlite").is_file():
        return MemoryAdvisor({}, {}, explore=explore) if explore > 0 else None
    with MemoryStore.open(root) as memory:
        return MemoryAdvisor.from_store(memory, explore=explore)


def _load_binding(root, task):
    if not task.candidate_systems:
        return None
    try:
        return BindingStore(root).load(task.candidate_systems[0])
    except Exception:
        return None
