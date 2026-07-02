"""Load and validate the four kernel registries under ``registry/``.

Read-only. No model execution, no team formation — this module only turns YAML
files into validated Python lists and raises clear errors when the contract is
violated.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Set

from ammo.registry.errors import RegistryError, ValidationError

API_VERSION = "ammo/v1"

# filename -> (expected `kind`, top-level list key)
_REGISTRY_SPEC = {
    "systems.yaml": ("SystemRegistry", "systems"),
    "models.yaml": ("ModelRegistry", "models"),
    "tools.yaml": ("ToolRegistry", "tools"),
    "roles.yaml": ("RoleRegistry", "roles"),
}


def _require_yaml():
    try:
        import yaml
    except ImportError as exc:  # pragma: no cover - message-only path
        raise RegistryError(
            "PyYAML is required to read AMMO registries. "
            "Install it with `pip install -e .` (PyYAML is a dependency)."
        ) from exc
    return yaml


def load_yaml_mapping(path: Path) -> Dict[str, Any]:
    """Parse a YAML file that must contain a top-level mapping."""
    yaml = _require_yaml()
    path = Path(path)
    if not path.is_file():
        raise RegistryError(f"file not found: {path}")
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ValidationError(f"{path}: invalid YAML — {exc}") from exc
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ValidationError(
            f"{path}: expected a mapping at the top level, got {type(data).__name__}"
        )
    return data


def load_registry(root: Path, filename: str) -> List[Dict[str, Any]]:
    """Load one ``registry/<filename>`` and return its validated entry list."""
    if filename not in _REGISTRY_SPEC:
        raise RegistryError(f"unknown registry file: {filename}")
    expected_kind, list_key = _REGISTRY_SPEC[filename]
    path = Path(root) / "registry" / filename
    data = load_yaml_mapping(path)

    if data.get("apiVersion") != API_VERSION:
        raise ValidationError(
            f"{path}: apiVersion must be '{API_VERSION}', got {data.get('apiVersion')!r}"
        )
    if data.get("kind") != expected_kind:
        raise ValidationError(
            f"{path}: kind must be '{expected_kind}', got {data.get('kind')!r}"
        )

    entries = data.get(list_key, [])
    if not isinstance(entries, list):
        raise ValidationError(f"{path}: '{list_key}' must be a list")
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict) or "id" not in entry:
            raise ValidationError(
                f"{path}: {list_key}[{index}] must be a mapping with an 'id' field"
            )
    return entries


def load_systems(root: Path) -> List[Dict[str, Any]]:
    return load_registry(root, "systems.yaml")


def load_models(root: Path) -> List[Dict[str, Any]]:
    return load_registry(root, "models.yaml")


def load_tools(root: Path) -> List[Dict[str, Any]]:
    return load_registry(root, "tools.yaml")


def load_roles(root: Path) -> List[Dict[str, Any]]:
    return load_registry(root, "roles.yaml")


def enabled_systems(root: Path) -> List[Dict[str, Any]]:
    """Only the systems whose ``enabled`` flag is truthy."""
    return [s for s in load_systems(root) if s.get("enabled", False)]


def registry_ids(root: Path, filename: str) -> Set[str]:
    """The set of ``id`` values declared in a registry file."""
    return {entry["id"] for entry in load_registry(root, filename)}
