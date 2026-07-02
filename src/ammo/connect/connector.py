"""Connect directories to AMMO as system packs — non-destructively.

`new_system` scaffolds a fresh in-tree pack. `connect` attaches an EXTERNAL
directory by reference (`source_path`) — it is never moved or copied. `disconnect`
removes only the AMMO-created descriptor under `systems/<id>/`; it never touches
the mounted source directory (constitution rule 9).
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path
from typing import List, Optional

from ammo import pack_contract as pc
from ammo.connect.templates import render_pack_files
from ammo.registry import registry_ids

_ID_RE = re.compile(r"[A-Za-z0-9._-]+")


class ConnectError(Exception):
    """A connect/new-system/disconnect operation could not be completed."""


def _validate_id(system_id: str) -> str:
    if not system_id or not _ID_RE.fullmatch(system_id):
        raise ConnectError(
            f"invalid system id {system_id!r}: use letters, digits, '.', '_', '-' only"
        )
    return system_id


class SystemConnector:
    def __init__(self, root: Path):
        self.root = Path(root)
        self.systems_root = self.root / "systems"

    def _write_pack(self, system_id: str, files: dict) -> Path:
        pack_dir = self.systems_root / system_id
        if pack_dir.exists():
            raise ConnectError(f"system '{system_id}' already exists at {pack_dir}")
        (pack_dir / pc.AMMO_DIR).mkdir(parents=True)
        for rel, content in files.items():
            path = pack_dir / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
        return pack_dir

    def _known_tools(self, tools: Optional[List[str]]) -> None:
        if not tools:
            return
        known = registry_ids(self.root, "tools.yaml")
        unknown = [t for t in tools if t not in known]
        if unknown:
            raise ConnectError(f"unknown tools (not in registry/tools.yaml): {unknown}")

    def new_system(self, system_id: str, *, description: Optional[str] = None) -> Path:
        _validate_id(system_id)
        files = render_pack_files(system_id, source_path=None, description=description)
        return self._write_pack(system_id, files)

    def connect(
        self,
        source_path,
        *,
        system_id: Optional[str] = None,
        writable: bool = True,
        tools: Optional[List[str]] = None,
        description: Optional[str] = None,
    ) -> Path:
        src = Path(source_path).expanduser()
        if not src.is_dir():
            raise ConnectError(f"source path is not an existing directory: {src}")
        src = src.resolve()

        system_id = _validate_id(system_id or src.name)
        self._known_tools(tools)
        files = render_pack_files(
            system_id,
            source_path=str(src),
            writable=writable,
            tools=tools,
            description=description,
        )
        return self._write_pack(system_id, files)

    def adopt(self, system_id: str, *, description: Optional[str] = None) -> dict:
        """Idempotently bring `systems/<id>` up to contract, preserving everything.

        Existing files are NEVER overwritten. Missing required/optional pack files
        are created from defaults. Works on a folder that may already contain the
        user's own content.
        """
        _validate_id(system_id)
        pack_dir = self.systems_root / system_id
        (pack_dir / pc.AMMO_DIR).mkdir(parents=True, exist_ok=True)

        files = render_pack_files(system_id, source_path=None, description=description)
        added: List[str] = []
        preserved: List[str] = []
        for rel, content in files.items():
            path = pack_dir / rel
            if path.exists():
                preserved.append(rel)
                continue
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
            added.append(rel)
        return {"path": pack_dir, "added": sorted(added), "preserved": sorted(preserved)}

    def disconnect(self, system_id: str) -> Path:
        _validate_id(system_id)
        pack_dir = self.systems_root / system_id
        if not (pack_dir / pc.AMMO_DIR).is_dir():
            raise ConnectError(f"no AMMO system pack named '{system_id}' under {self.systems_root}")
        # Only ever removes the in-repo descriptor. The mounted source is untouched.
        shutil.rmtree(pack_dir)
        return pack_dir
