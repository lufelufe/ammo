"""Locate the AMMO root directory.

The AMMO root is the directory that holds the data substrate the kernel governs
(``systems/``, ``registry/``, ``memory/``, ``runtime/``, ``vaults/``). This
module only *finds* it — it performs no execution and reads no pack contents.

Resolution order:
1. ``AMMO_ROOT`` environment variable (explicit override).
2. Walk up from ``start`` (or the current working directory) to the first
   directory that looks like an AMMO root.
3. Fall back to the repository root that ships this package.
4. Last resort: the starting directory.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

ENV_VAR = "AMMO_ROOT"


def looks_like_root(path: Path) -> bool:
    """A directory looks like an AMMO root if it holds systems/ and registry/."""
    return (path / "systems").is_dir() and (path / "registry").is_dir()


def find_ammo_root(start: Optional[Path] = None) -> Path:
    """Resolve the AMMO root directory (see module docstring for the order)."""
    override = os.environ.get(ENV_VAR)
    if override:
        return Path(override).expanduser().resolve()

    start = (start or Path.cwd()).resolve()
    for candidate in (start, *start.parents):
        if looks_like_root(candidate):
            return candidate

    # src/ammo/paths.py -> parents[2] is the repository root.
    pkg_root = Path(__file__).resolve().parents[2]
    if looks_like_root(pkg_root):
        return pkg_root

    return start
