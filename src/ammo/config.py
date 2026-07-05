"""AMMO machine-local configuration (`ammo.config.yaml` at the AMMO root).

Written by the summon wizard (`ammo start`). Machine-specific — the file is
git-ignored. Holds no secrets: host id, primary model, preferred model set, and
the default optimization objective.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

CONFIG_FILE = "ammo.config.yaml"


@dataclass
class AmmoConfig:
    host: str = "terminal"                 # summoning environment id
    primary_provider: Optional[str] = None
    primary_model: Optional[str] = None
    models: List[str] = field(default_factory=list)   # preferred model set
    default_objective: str = "balanced"
    # user-authored role assignment (slot id -> model id): who plays
    # orchestrator / critic / worker / builder. See ammo.roleplan.
    roles: Dict[str, str] = field(default_factory=dict)
    # learned confidence correction (`ammo calibrate --apply`): a bounded
    # global offset derived from the user's good/bad verdicts, applied by the
    # Confidence Engine so scores track ground truth. 0.0 = uncalibrated.
    confidence_offset: float = 0.0
    configured_at: str = ""

    def to_dict(self):
        return {
            "apiVersion": "ammo/v1",
            "kind": "Config",
            "host": self.host,
            "primary_provider": self.primary_provider,
            "primary_model": self.primary_model,
            "models": self.models,
            "default_objective": self.default_objective,
            "roles": self.roles,
            "confidence_offset": self.confidence_offset,
            "configured_at": self.configured_at,
        }


def config_path(root: Path) -> Path:
    return Path(root) / CONFIG_FILE


def load_config(root: Path) -> Optional[AmmoConfig]:
    path = config_path(root)
    if not path.is_file():
        return None
    import yaml

    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return AmmoConfig(
        host=data.get("host", "terminal"),
        primary_provider=data.get("primary_provider"),
        primary_model=data.get("primary_model"),
        models=list(data.get("models") or []),
        default_objective=data.get("default_objective", "balanced"),
        roles={str(k): str(v) for k, v in (data.get("roles") or {}).items() if v},
        confidence_offset=float(data.get("confidence_offset") or 0.0),
        configured_at=str(data.get("configured_at", "")),
    )


def save_config(root: Path, config: AmmoConfig) -> Path:
    import yaml

    path = config_path(root)
    header = "# AMMO machine-local config — written by `ammo start`. No secrets.\n"
    path.write_text(header + yaml.safe_dump(config.to_dict(), sort_keys=False),
                    encoding="utf-8")
    return path
