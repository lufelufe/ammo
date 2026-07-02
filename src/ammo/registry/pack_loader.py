"""Load and validate a single system pack (``systems/<id>/``).

A :class:`SystemPack` is the in-memory form of a pack's ``.ammo/`` meta layer
plus its ``system.md``. The loader reads the files, then validates the contract
(apiVersion, manifest id == folder name, and cross-references into the kernel
registries). It performs no model execution and no team formation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from ammo import pack_contract as pc
from ammo.registry.errors import PackNotFoundError, ValidationError
from ammo.registry.loaders import API_VERSION, load_yaml_mapping, registry_ids

# (.ammo filename, SystemPack attribute)
_AMMO_FILES = (
    ("manifest.yaml", "manifest"),
    ("routing.yaml", "routing"),
    ("memory_map.yaml", "memory_map"),
    ("permissions.yaml", "permissions"),
    ("workflows.yaml", "workflows"),
)


@dataclass
class SystemPack:
    """A loaded, validated system pack."""

    id: str
    path: Path
    manifest: Dict[str, Any]
    routing: Dict[str, Any]
    memory_map: Dict[str, Any]
    permissions: Dict[str, Any]
    workflows: Dict[str, Any]
    system_md: str
    # optional per-system optimization specs (empty/None when absent)
    preferences: Dict[str, Any] = field(default_factory=dict)
    verification: Dict[str, Any] = field(default_factory=dict)
    limits: Dict[str, Any] = field(default_factory=dict)
    context: Optional[str] = None

    @property
    def name(self) -> str:
        return self.manifest.get("name", self.id)

    @property
    def version(self) -> str:
        return str(self.manifest.get("version", ""))

    @property
    def status(self) -> str:
        return self.manifest.get("status", "")

    @property
    def source_path(self) -> Optional[str]:
        return self.manifest.get("source_path")

    @property
    def mounted(self) -> bool:
        return bool(self.manifest.get("mounted"))

    @property
    def description(self) -> str:
        return self.manifest.get("description", "")

    @property
    def capabilities(self) -> List[Dict[str, Any]]:
        return self.manifest.get("capabilities") or []

    @property
    def default_roles(self) -> List[str]:
        return self.routing.get("default_roles") or []

    @property
    def workflow_list(self) -> List[Dict[str, Any]]:
        return self.workflows.get("workflows") or []

    def referenced_roles(self) -> set:
        """Every role id this pack names in routing + workflows."""
        roles = set(self.default_roles)
        escalation = (self.routing.get("escalation") or {}).get("on_low_confidence", "")
        if isinstance(escalation, str) and escalation.startswith("add_role:"):
            roles.add(escalation.split(":", 1)[1])
        for workflow in self.workflow_list:
            for stage in workflow.get("stages") or []:
                if stage.get("role"):
                    roles.add(stage["role"])
        return roles

    def summary_lines(self) -> List[str]:
        """A structured, human-readable summary (used by ``inspect-system``)."""
        lines: List[str] = []
        header = f"System pack: {self.id}  ({self.name} v{self.version})"
        if self.status:
            header += f" [{self.status}]"
        lines.append(header)
        lines.append(f"  path: {self.path}")
        if self.description:
            lines.append(f"  description: {self.description.strip()}")

        lines.append("  capabilities:")
        for cap in self.capabilities:
            lines.append(f"    - {cap.get('id', '?')}: {cap.get('summary', '')}".rstrip())

        match = self.routing.get("match") or {}
        lines.append("  routing:")
        lines.append(f"    priority: {self.routing.get('priority', '')}")
        lines.append(f"    intents: {', '.join(match.get('intents', []) or []) or '(none)'}")
        lines.append(f"    default_roles: {', '.join(self.default_roles) or '(none)'}")

        stores = list((self.memory_map.get("stores") or {}).keys())
        vaults = [vb.get("vault") for vb in (self.memory_map.get("vault_bindings") or [])]
        lines.append("  memory:")
        lines.append(f"    namespace: {self.memory_map.get('namespace', '')}")
        lines.append(f"    stores: {', '.join(stores) or '(none)'}")
        lines.append(f"    vaults: {', '.join(v for v in vaults if v) or '(none)'}")

        perms = self.permissions
        lines.append("  permissions:")
        lines.append(f"    network: {(perms.get('network') or {}).get('allow', False)}")
        lines.append(
            f"    tools: {', '.join((perms.get('tools') or {}).get('allow', [])) or '(none)'}"
        )
        lines.append(
            f"    models: {', '.join((perms.get('models') or {}).get('allow', [])) or '(none)'}"
        )
        lines.append(
            f"    roles: {', '.join((perms.get('roles') or {}).get('allow', [])) or '(none)'}"
        )

        lines.append("  workflows:")
        for workflow in self.workflow_list:
            stages = " -> ".join(
                s.get("role", "?") for s in (workflow.get("stages") or [])
            )
            gate = workflow.get("confidence_gate")
            gate_str = f" (gate {gate})" if gate is not None else ""
            lines.append(f"    - {workflow.get('id', '?')}{gate_str}: {stages}")

        return lines


class SystemPackLoader:
    """Loads system packs from an AMMO root and validates them."""

    def __init__(self, root: Path):
        self.root = Path(root)
        self.systems_root = self.root / "systems"

    def available(self) -> List[str]:
        return pc.discover_pack_ids(self.systems_root)

    def load(self, system_id: str) -> SystemPack:
        pack_dir = self.systems_root / system_id
        ammo_dir = pack_dir / pc.AMMO_DIR
        if not pack_dir.is_dir() or not ammo_dir.is_dir():
            available = ", ".join(self.available()) or "none"
            raise PackNotFoundError(
                f"system pack '{system_id}' not found under {self.systems_root} "
                f"(available: {available})"
            )

        for name in pc.REQUIRED_ROOT_FILES:
            if not (pack_dir / name).is_file():
                raise ValidationError(f"{pack_dir}: missing required file '{name}'")
        system_md_path = pack_dir / "system.md"

        loaded = {
            attr: load_yaml_mapping(ammo_dir / filename)
            for filename, attr in _AMMO_FILES
        }
        pack = SystemPack(
            id=system_id,
            path=pack_dir,
            system_md=system_md_path.read_text(encoding="utf-8"),
            **loaded,
        )
        self._load_optional(pack, ammo_dir, pack_dir)
        self._validate(pack)
        return pack

    def _load_optional(self, pack: SystemPack, ammo_dir: Path, pack_dir: Path) -> None:
        for filename, attr in (
            ("preferences.yaml", "preferences"),
            ("verification.yaml", "verification"),
            ("limits.yaml", "limits"),
        ):
            path = ammo_dir / filename
            if path.is_file():
                setattr(pack, attr, load_yaml_mapping(path))
        context_path = pack_dir / "context.md"
        if context_path.is_file():
            pack.context = context_path.read_text(encoding="utf-8")

    def load_all(self) -> List[SystemPack]:
        return [self.load(system_id) for system_id in self.available()]

    def _validate(self, pack: SystemPack) -> None:
        ammo_dir = pack.path / pc.AMMO_DIR
        files = {
            "manifest.yaml": pack.manifest,
            "routing.yaml": pack.routing,
            "memory_map.yaml": pack.memory_map,
            "permissions.yaml": pack.permissions,
            "workflows.yaml": pack.workflows,
        }
        for filename, data in files.items():
            if data.get("apiVersion") != API_VERSION:
                raise ValidationError(
                    f"{ammo_dir / filename}: apiVersion must be '{API_VERSION}', "
                    f"got {data.get('apiVersion')!r}"
                )

        manifest_id = pack.manifest.get("id")
        if manifest_id != pack.id:
            raise ValidationError(
                f"{ammo_dir / 'manifest.yaml'}: id {manifest_id!r} must equal "
                f"the folder name {pack.id!r}"
            )

        known_roles = registry_ids(self.root, "roles.yaml")
        known_tools = registry_ids(self.root, "tools.yaml")
        known_models = registry_ids(self.root, "models.yaml")

        unknown_roles = pack.referenced_roles() - known_roles
        if unknown_roles:
            raise ValidationError(
                f"{pack.path}: references roles not in registry/roles.yaml: "
                f"{sorted(unknown_roles)}"
            )

        perms = pack.permissions
        tool_allow = set((perms.get("tools") or {}).get("allow", []))
        role_allow = set((perms.get("roles") or {}).get("allow", []))
        model_allow = set((perms.get("models") or {}).get("allow", []))

        if tool_allow - known_tools:
            raise ValidationError(
                f"{ammo_dir / 'permissions.yaml'}: allows tools not in "
                f"registry/tools.yaml: {sorted(tool_allow - known_tools)}"
            )
        if role_allow - known_roles:
            raise ValidationError(
                f"{ammo_dir / 'permissions.yaml'}: allows roles not in "
                f"registry/roles.yaml: {sorted(role_allow - known_roles)}"
            )
        unknown_models = {m for m in model_allow if m != "*"} - known_models
        if unknown_models:
            raise ValidationError(
                f"{ammo_dir / 'permissions.yaml'}: allows models not in "
                f"registry/models.yaml: {sorted(unknown_models)}"
            )
