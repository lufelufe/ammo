"""AMMO self-inspection (``ammo doctor``).

Verifies that an AMMO root is structurally healthy: required folders, registry
files, and system packs exist, and that the runtime/memory data folders are
writable. This module does **not** execute models and does **not** read or
mutate personal/investment pack contents — it only checks structure and probes
writability with a temporary file it immediately removes.
"""

from __future__ import annotations

import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Tuple

from ammo import pack_contract as pc


@dataclass
class Check:
    """One structural check and its result."""

    name: str
    ok: bool
    detail: str = ""


@dataclass
class DoctorReport:
    root: Path
    checks: List[Check] = field(default_factory=list)
    notices: List[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return all(c.ok for c in self.checks)

    @property
    def failures(self) -> List[Check]:
        return [c for c in self.checks if not c.ok]

    def add(self, name: str, ok: bool, detail: str = "") -> bool:
        self.checks.append(Check(name=name, ok=ok, detail=detail))
        return ok


def _is_writable(directory: Path) -> Tuple[bool, str]:
    if not directory.is_dir():
        return False, f"{directory} is not a directory"
    try:
        with tempfile.NamedTemporaryFile(
            dir=directory, prefix=".ammo-doctor-", delete=True
        ):
            pass
    except OSError as exc:
        return False, f"not writable: {exc}"
    return True, str(directory)


def run_doctor(root: Path) -> DoctorReport:
    """Run every structural check against ``root`` and return a report."""
    root = Path(root)
    report = DoctorReport(root=root)

    report.add("AMMO root exists", root.is_dir(), str(root))

    for name in pc.REQUIRED_TOP_LEVEL_DIRS:
        path = root / name
        report.add(f"dir: {name}/", path.is_dir(), str(path))

    for name in pc.REQUIRED_REGISTRY_FILES:
        path = root / "registry" / name
        report.add(f"registry: {name}", path.is_file(), str(path))

    systems_root = root / "systems"
    discovered = pc.discover_pack_ids(systems_root)

    for system_id in pc.EXPECTED_SYSTEMS:
        report.add(
            f"system pack: {system_id}",
            system_id in discovered,
            str(systems_root / system_id),
        )

    for system_id in discovered:
        missing = pc.missing_pack_files(systems_root, system_id)
        detail = (
            "ok"
            if not missing
            else "missing " + ", ".join(str(p.relative_to(root)) for p in missing)
        )
        report.add(f"pack files: {system_id}", not missing, detail)

    # mounted packs: the referenced source directory must still exist
    for system_id in discovered:
        source = _mount_source(systems_root / system_id)
        if source:
            report.add(f"mount: {system_id}", Path(source).is_dir(), source)

    for name in pc.WRITABLE_DIRS:
        ok, detail = _is_writable(root / name)
        report.add(f"writable: {name}/", ok, detail)

    # informational: bare folders under systems/ that AMMO hasn't adopted
    if systems_root.is_dir():
        for child in sorted(systems_root.iterdir()):
            if child.is_dir() and not (child / pc.AMMO_DIR).is_dir():
                report.notices.append(
                    f"systems/{child.name}/ has no .ammo — run "
                    f"`ammo new-system {child.name}` or "
                    f"`ammo connect <path> --id {child.name}`"
                )

    return report


def _mount_source(pack_dir: Path) -> Optional[str]:
    """Return a pack's manifest source_path if it is a mount, else None."""
    manifest = pack_dir / pc.AMMO_DIR / "manifest.yaml"
    if not manifest.is_file():
        return None
    try:
        from ammo.registry.loaders import load_yaml_mapping

        return load_yaml_mapping(manifest).get("source_path")
    except Exception:
        return None
