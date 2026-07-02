"""Per-system model binding — which models (and roles) a system uses.

A binding is the outcome of the model-selection wizard: the allowed model set for
a system (each with its provider) and, optionally, an explicit role->model team
to reuse. Stored at ``systems/<id>/.ammo/binding.yaml``. No secrets.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from ammo import pack_contract as pc

BINDING_FILE = "binding.yaml"


@dataclass
class Binding:
    system: str
    allow_paid: bool = False
    models: List[Dict[str, str]] = field(default_factory=list)  # [{id, provider}]
    team: List[Dict[str, str]] = field(default_factory=list)    # [{role, model}]

    @property
    def model_ids(self) -> List[str]:
        return [m["id"] for m in self.models if m.get("id")]

    @property
    def team_map(self) -> Dict[str, str]:
        return {t["role"]: t["model"] for t in self.team if t.get("role") and t.get("model")}

    def to_dict(self) -> Dict[str, Any]:
        return {
            "apiVersion": "ammo/v1",
            "kind": "Binding",
            "system": self.system,
            "allow_paid": self.allow_paid,
            "models": self.models,
            "team": self.team,
        }

    @classmethod
    def from_dict(cls, system: str, data: Dict[str, Any]) -> "Binding":
        return cls(
            system=system,
            allow_paid=bool(data.get("allow_paid", False)),
            models=list(data.get("models") or []),
            team=list(data.get("team") or []),
        )


class BindingStore:
    def __init__(self, root: Path):
        self.root = Path(root)

    def _path(self, system_id: str) -> Path:
        return self.root / "systems" / system_id / pc.AMMO_DIR / BINDING_FILE

    def exists(self, system_id: str) -> bool:
        return self._path(system_id).is_file()

    def load(self, system_id: str) -> Optional[Binding]:
        path = self._path(system_id)
        if not path.is_file():
            return None
        import yaml

        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        return Binding.from_dict(system_id, data)

    def save(self, binding: Binding) -> Path:
        import yaml

        path = self._path(binding.system)
        path.parent.mkdir(parents=True, exist_ok=True)
        header = "# binding.yaml — per-system model binding (managed by `ammo bind`).\n"
        path.write_text(header + yaml.safe_dump(binding.to_dict(), sort_keys=False), encoding="utf-8")
        return path
