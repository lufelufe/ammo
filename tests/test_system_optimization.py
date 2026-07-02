"""Tests for per-system optimization specs + idempotent adopt (Milestone 13)."""

import os
from pathlib import Path

import pytest

from ammo import cli, pack_contract as pc
from ammo.connect import SystemConnector
from ammo.registry import SystemPackLoader

REPO_ROOT = Path(__file__).resolve().parents[1]

OPTIONAL = [".ammo/preferences.yaml", ".ammo/verification.yaml", ".ammo/limits.yaml",
            "context.md", ".ammoignore"]


@pytest.fixture
def root(tmp_path):
    r = tmp_path / "root"
    r.mkdir()
    os.symlink(REPO_ROOT / "registry", r / "registry")
    for name in ("systems", "runtime", "memory", "vaults"):
        (r / name).mkdir()
    return r


# --- optimization specs -----------------------------------------------------

def test_new_pack_includes_optimization_specs(root):
    SystemConnector(root).new_system("demo")
    pack_dir = root / "systems" / "demo"
    for rel in OPTIONAL:
        assert (pack_dir / rel).is_file(), rel


def test_loader_reads_optional_specs(root):
    SystemConnector(root).new_system("demo")
    pack = SystemPackLoader(root).load("demo")
    assert isinstance(pack.preferences, dict) and pack.preferences.get("system") == "demo"
    assert pack.verification.get("kind") == "Verification"
    assert pack.limits.get("confidence_gate") == 0.6
    assert pack.context and "Operating context" in pack.context


def test_optional_specs_are_not_required(root):
    # a pack with only the 5 required files still validates
    SystemConnector(root).new_system("demo")
    ammo = root / "systems" / "demo" / pc.AMMO_DIR
    for name in pc.OPTIONAL_AMMO_FILES:
        (ammo / name).unlink()
    (root / "systems" / "demo" / "context.md").unlink()
    pack = SystemPackLoader(root).load("demo")  # must not raise
    assert pack.preferences == {} and pack.context is None


# --- adopt (idempotent, non-destructive) -----------------------------------

def test_adopt_preserves_existing_content(root):
    x = root / "systems" / "x"
    x.mkdir()
    (x / "NOTES.md").write_text("keep me", encoding="utf-8")

    result = SystemConnector(root).adopt("x")
    assert (x / "NOTES.md").read_text(encoding="utf-8") == "keep me"  # untouched
    for name in pc.REQUIRED_AMMO_FILES:
        assert (x / pc.AMMO_DIR / name).is_file()
    assert ".ammo/manifest.yaml" in result["added"]


def test_adopt_is_idempotent(root):
    SystemConnector(root).adopt("x")
    second = SystemConnector(root).adopt("x")
    assert second["added"] == []
    assert ".ammo/manifest.yaml" in second["preserved"]


def test_adopt_does_not_overwrite_hand_edited_file(root):
    conn = SystemConnector(root)
    conn.adopt("x")
    manifest = root / "systems" / "x" / pc.AMMO_DIR / "manifest.yaml"
    manifest.write_text("apiVersion: ammo/v1\nkind: SystemPack\nid: x\ncustom: edited\n",
                        encoding="utf-8")
    conn.adopt("x")  # again
    assert "custom: edited" in manifest.read_text(encoding="utf-8")  # preserved


# --- CLI --------------------------------------------------------------------

@pytest.fixture
def ammo_root(root, monkeypatch):
    monkeypatch.setenv("AMMO_ROOT", str(root))
    return root


def test_cli_adopt(ammo_root, capsys):
    (ammo_root / "systems" / "x").mkdir()
    (ammo_root / "systems" / "x" / "data.txt").write_text("hi", encoding="utf-8")
    assert cli.main(["adopt", "x"]) == 0
    out = capsys.readouterr().out
    assert "Adopted system pack" in out and "added:" in out
    assert (ammo_root / "systems" / "x" / "data.txt").read_text(encoding="utf-8") == "hi"
    assert SystemPackLoader(ammo_root).load("x").limits.get("confidence_gate") == 0.6
