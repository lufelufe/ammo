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


def expand_model_entries(entries: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Expand family model entries into per-engine nodes.

    A model entry may declare ``engines: [claude_a, claude_b]`` with a
    family-level ``id`` (e.g. ``opus``): every engine that can serve the model
    gets its own node ``{engine}_{id}`` sharing the family metadata. This is
    what makes the catalog complete by construction — an engine offers ALL the
    models of its family, never a hand-picked per-account subset. Entries
    without ``engines`` are plain nodes and pass through unchanged.
    """
    expanded: List[Dict[str, Any]] = []
    for entry in entries:
        engines = entry.get("engines")
        if not engines:
            expanded.append(entry)
            continue
        if not isinstance(engines, list) or not all(isinstance(e, str) for e in engines):
            raise ValidationError(
                f"models.yaml: entry '{entry['id']}' has a non-list 'engines' field"
            )
        for engine in engines:
            node = dict(entry)
            del node["engines"]
            node["engine"] = engine
            node["model"] = entry["id"]
            node["id"] = f"{engine}_{entry['id']}"
            expanded.append(node)
    seen: Set[str] = set()
    for node in expanded:
        if node["id"] in seen:
            raise ValidationError(
                f"models.yaml: duplicate model id '{node['id']}' after engine expansion"
            )
        seen.add(node["id"])
    return expanded


def load_systems(root: Path) -> List[Dict[str, Any]]:
    return load_registry(root, "systems.yaml")


def load_models(root: Path) -> List[Dict[str, Any]]:
    return expand_model_entries(load_registry(root, "models.yaml"))


def load_tools(root: Path) -> List[Dict[str, Any]]:
    return load_registry(root, "tools.yaml")


def load_roles(root: Path) -> List[Dict[str, Any]]:
    return load_registry(root, "roles.yaml")


def enabled_systems(root: Path) -> List[Dict[str, Any]]:
    """Only the systems whose ``enabled`` flag is truthy."""
    return [s for s in load_systems(root) if s.get("enabled", False)]


def registry_ids(root: Path, filename: str) -> Set[str]:
    """The set of ``id`` values declared in a registry file (models: expanded)."""
    if filename == "models.yaml":
        return {entry["id"] for entry in load_models(root)}
    return {entry["id"] for entry in load_registry(root, filename)}
