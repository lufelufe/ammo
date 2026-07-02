"""Tests for `ammo doctor` and `ammo list-systems` (Milestone 2).

These exercise the real repository root (integration) and synthetic roots built
in a temp dir (unit), asserting behavior/invariants rather than snapshots.
"""

import os
from pathlib import Path

import pytest

from ammo import cli, pack_contract as pc
from ammo.doctor import run_doctor
from ammo.paths import find_ammo_root, looks_like_root
from ammo.registry import enabled_systems, load_systems

REPO_ROOT = Path(__file__).resolve().parents[1]


def _make_valid_root(base: Path) -> Path:
    """Build a minimal but structurally-valid AMMO root under `base`."""
    root = base / "ammo_root"
    for name in pc.REQUIRED_TOP_LEVEL_DIRS:
        (root / name).mkdir(parents=True, exist_ok=True)
    for name in pc.REQUIRED_REGISTRY_FILES:
        (root / "registry" / name).write_text("apiVersion: ammo/v1\n", encoding="utf-8")
    for system_id in pc.EXPECTED_SYSTEMS:
        ammo_dir = root / "systems" / system_id / pc.AMMO_DIR
        ammo_dir.mkdir(parents=True, exist_ok=True)
        for name in pc.REQUIRED_AMMO_FILES:
            (ammo_dir / name).write_text("apiVersion: ammo/v1\n", encoding="utf-8")
        (root / "systems" / system_id / "system.md").write_text(
            f"# {system_id}\n", encoding="utf-8"
        )
    return root


# --- doctor: real repository ------------------------------------------------

def test_doctor_passes_on_real_repo():
    report = run_doctor(REPO_ROOT)
    assert report.ok, [f"{c.name}: {c.detail}" for c in report.failures]


# --- doctor: synthetic roots ------------------------------------------------

def test_doctor_healthy_synthetic_root(tmp_path):
    root = _make_valid_root(tmp_path)
    report = run_doctor(root)
    assert report.ok
    assert report.checks  # not empty


def test_doctor_detects_missing_registry_file(tmp_path):
    root = _make_valid_root(tmp_path)
    (root / "registry" / "models.yaml").unlink()
    report = run_doctor(root)
    assert not report.ok
    assert any("models.yaml" in c.name and not c.ok for c in report.checks)


def test_doctor_detects_missing_top_level_dir(tmp_path):
    root = _make_valid_root(tmp_path)
    # remove a writable data dir entirely
    import shutil

    shutil.rmtree(root / "runtime")
    report = run_doctor(root)
    assert not report.ok
    assert any(c.name == "dir: runtime/" and not c.ok for c in report.checks)


def test_doctor_detects_missing_pack_file(tmp_path):
    root = _make_valid_root(tmp_path)
    (root / "systems" / "personal" / pc.AMMO_DIR / "routing.yaml").unlink()
    report = run_doctor(root)
    assert not report.ok
    assert any(c.name == "pack files: personal" and not c.ok for c in report.checks)


def test_doctor_reports_writable_dirs(tmp_path):
    root = _make_valid_root(tmp_path)
    report = run_doctor(root)
    writable = {c.name: c.ok for c in report.checks if c.name.startswith("writable:")}
    assert writable == {"writable: runtime/": True, "writable: memory/": True}


# --- root resolution --------------------------------------------------------

def test_find_ammo_root_env_override(tmp_path, monkeypatch):
    target = tmp_path / "somewhere"
    target.mkdir()
    monkeypatch.setenv("AMMO_ROOT", str(target))
    assert find_ammo_root() == target.resolve()


def test_find_ammo_root_walks_up(tmp_path, monkeypatch):
    root = _make_valid_root(tmp_path)
    nested = root / "systems" / "personal"
    monkeypatch.delenv("AMMO_ROOT", raising=False)
    assert find_ammo_root(start=nested) == root.resolve()


def test_looks_like_root(tmp_path):
    assert not looks_like_root(tmp_path)
    root = _make_valid_root(tmp_path)
    assert looks_like_root(root)


# --- registry / list-systems ------------------------------------------------

def test_enabled_systems_on_real_repo():
    systems = enabled_systems(REPO_ROOT)
    ids = {s["id"] for s in systems}
    assert set(pc.EXPECTED_SYSTEMS).issubset(ids)
    assert all(s.get("enabled") for s in systems)


def test_load_systems_returns_all_entries():
    all_systems = load_systems(REPO_ROOT)
    assert len(all_systems) >= len(pc.EXPECTED_SYSTEMS)


# --- CLI wiring -------------------------------------------------------------

def test_cli_doctor_exit_zero_on_real_repo(monkeypatch, capsys):
    monkeypatch.setenv("AMMO_ROOT", str(REPO_ROOT))
    code = cli.main(["doctor"])
    out = capsys.readouterr().out
    assert code == 0
    assert "checks passed" in out
    assert "healthy" in out


def test_cli_doctor_exit_one_on_broken_root(tmp_path, monkeypatch, capsys):
    root = _make_valid_root(tmp_path)
    (root / "registry" / "roles.yaml").unlink()
    monkeypatch.setenv("AMMO_ROOT", str(root))
    code = cli.main(["doctor"])
    out = capsys.readouterr().out
    assert code == 1
    assert "✗" in out


def test_cli_list_systems(monkeypatch, capsys):
    monkeypatch.setenv("AMMO_ROOT", str(REPO_ROOT))
    code = cli.main(["list-systems"])
    out = capsys.readouterr().out
    assert code == 0
    assert "Enabled systems:" in out
    for system_id in pc.EXPECTED_SYSTEMS:
        assert system_id in out
