"""Role-bound working directories.

Traces and data are bound to the role (per system), not the model. See
``RoleWorkspace``.
"""

from ammo.roles.workspace import RoleWorkspace

__all__ = ["RoleWorkspace"]
