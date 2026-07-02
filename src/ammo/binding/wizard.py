"""Decision logic for the model-selection wizard (pure, testable).

Separates *what to decide* from *how to prompt*. The CLI wraps these with input()
for the interactive flow; tests call them directly.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from ammo.binding.store import Binding, BindingStore


def existing_or_best(root: Path, system_id: str) -> Optional[Dict[str, Any]]:
    """A proposal to reuse: the current binding, else the memory-best team.

    Returns a dict {source, binding} or None if there is nothing to reuse (so the
    wizard should run the full 1-2-3 selection).
    """
    store = BindingStore(root)
    existing = store.load(system_id)
    if existing and existing.models:
        return {"source": "existing_binding", "binding": existing}

    best = _memory_best(root, system_id)
    if best and best.get("team_signature"):
        team = _parse_signature(best["team_signature"])
        binding = Binding(
            system=system_id,
            models=[{"id": m, "provider": "unknown"} for m in sorted({t["model"] for t in team})],
            team=team,
        )
        return {"source": "memory_best", "binding": binding, "stats": best}
    return None


def available_choices(statuses, *, allow_paid: bool = False) -> List[Dict[str, str]]:
    """Flatten available providers into selectable (model, provider, cost) choices."""
    from ammo.providers import select_models

    usable = select_models(statuses, allow_paid=allow_paid)
    provider_kind = {s.profile.id: s.profile.kind for s in statuses}
    return [
        {"model": model_id, "provider": provider_id, "kind": provider_kind.get(provider_id, "?")}
        for model_id, provider_id in sorted(usable.items())
    ]


def build_binding(system_id: str, chosen: List[Dict[str, str]], *, allow_paid: bool = False,
                  team: Optional[List[Dict[str, str]]] = None) -> Binding:
    models = [{"id": c["model"], "provider": c.get("provider", "unknown")} for c in chosen]
    return Binding(system=system_id, allow_paid=allow_paid, models=models, team=team or [])


# -- helpers -----------------------------------------------------------------

def _memory_best(root: Path, system_id: str) -> Optional[Dict[str, Any]]:
    db = Path(root) / "memory" / "ammo.sqlite"
    if not db.is_file():
        return None
    from ammo.memory import MemoryStore

    with MemoryStore(db) as memory:
        return memory.best_team_for_system(system_id)


def _parse_signature(signature: str) -> List[Dict[str, str]]:
    team = []
    for token in signature.split("+"):
        if ":" in token:
            role, model = token.split(":", 1)
            team.append({"role": role, "model": model})
    return team
