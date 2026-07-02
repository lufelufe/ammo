"""AMMO declarative-layer loaders.

Reads and validates the kernel registries (``registry/*.yaml``) and system packs
(``systems/<id>/.ammo/*.yaml``). Read-only: no model execution, no team
formation. This is where AMMO learns *what systems live beneath it*.

Note: the code package ``ammo.registry`` is distinct from the top-level *data*
directory ``registry/`` it reads — same word, different namespaces.
"""

from ammo.registry.errors import (
    PackNotFoundError,
    RegistryError,
    ValidationError,
)
from ammo.registry.loaders import (
    API_VERSION,
    enabled_systems,
    load_models,
    load_registry,
    load_roles,
    load_systems,
    load_tools,
    load_yaml_mapping,
    registry_ids,
)
from ammo.registry.pack_loader import SystemPack, SystemPackLoader

__all__ = [
    "API_VERSION",
    "PackNotFoundError",
    "RegistryError",
    "ValidationError",
    "enabled_systems",
    "load_models",
    "load_registry",
    "load_roles",
    "load_systems",
    "load_tools",
    "load_yaml_mapping",
    "registry_ids",
    "SystemPack",
    "SystemPackLoader",
]
