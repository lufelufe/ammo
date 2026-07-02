"""Connect directories to AMMO as system packs (universal, non-destructive).

`new-system` scaffolds an in-tree pack; `connect` attaches any external directory
by reference; `disconnect` removes only the AMMO descriptor. This is what makes
AMMO universal: point it at a folder, grant scoped permissions, and it operates
there — without moving or copying your data.
"""

from ammo.connect.connector import ConnectError, SystemConnector

__all__ = ["SystemConnector", "ConnectError"]
