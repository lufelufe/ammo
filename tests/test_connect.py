"""Tests for System Connection & Permissions (Milestone 12)."""

import os
import sys
from pathlib import Path

import pytest

from ammo import cli, pack_contract as pc
from ammo.connect import ConnectError, SystemConnector
from ammo.doctor import run_doctor
from ammo.registry import SystemPackLoader

REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def root(tmp_path):
    """A temp AMMO root: registry symlinked (for validation), fresh systems/."""
    r = tmp_path / "root"
    r.mkdir()
    os.symlink(REPO_ROOT / "registry", r / "registry")
    (r / "systems").mkdir()
    for name in ("runtime", "memory", "vaults"):
        (r / name).mkdir()
    return r


@pytest.fixture
def external(tmp_path):
    ext = tmp_path / "myproject"
    ext.mkdir()
    (ext / "readme.txt").write_text("hi", encoding="utf-8")
    return ext


# --- new_system -------------------------------------------------------------

def test_new_system_creates_valid_pack(root):
    path = SystemConnector(root).new_system("demo")
    assert (path / pc.AMMO_DIR).is_dir()
    for name in pc.REQUIRED_AMMO_FILES:
        assert (path / pc.AMMO_DIR / name).is_file()
    # the generated pack passes full contract validation
    pack = SystemPackLoader(root).load("demo")
    assert pack.id == "demo" and pack.source_path is None


def test_new_system_rejects_duplicate_and_bad_id(root):
    SystemConnector(root).new_system("demo")
    with pytest.raises(ConnectError):
        SystemConnector(root).new_system("demo")
    with pytest.raises(ConnectError):
        SystemConnector(root).new_system("bad id/slash")


# --- connect (mount) --------------------------------------------------------

def test_connect_is_non_destructive_and_valid(root, external):
    path = SystemConnector(root).connect(external, system_id="myproject")
    pack = SystemPackLoader(root).load("myproject")
    assert pack.mounted is True
    assert pack.source_path == str(external.resolve())
    assert pack.status == "connected"
    # source is untouched and still there
    assert (external / "readme.txt").read_text(encoding="utf-8") == "hi"
    # writable by default -> source path is in the write scope
    write_scope = pack.permissions["filesystem"]["write"]
    assert str(external.resolve()) in write_scope


def test_connect_read_only_excludes_write_scope(root, external):
    SystemConnector(root).connect(external, system_id="ro", writable=False)
    pack = SystemPackLoader(root).load("ro")
    assert pack.manifest["writable"] is False
    assert str(external.resolve()) not in pack.permissions["filesystem"]["write"]
    assert pack.permissions["tools"]["allow"] == ["fs.read"]


def test_connect_defaults_id_to_folder_name(root, external):
    SystemConnector(root).connect(external)
    assert SystemPackLoader(root).load("myproject").id == "myproject"


def test_connect_rejects_missing_source_and_unknown_tools(root, external, tmp_path):
    with pytest.raises(ConnectError):
        SystemConnector(root).connect(tmp_path / "nope", system_id="x")
    with pytest.raises(ConnectError):
        SystemConnector(root).connect(external, system_id="x", tools=["not.a.tool"])


# --- disconnect -------------------------------------------------------------

def test_disconnect_removes_descriptor_only(root, external):
    SystemConnector(root).connect(external, system_id="myproject")
    SystemConnector(root).disconnect("myproject")
    assert not (root / "systems" / "myproject").exists()
    assert (external / "readme.txt").is_file()  # source untouched


def test_disconnect_unknown_raises(root):
    with pytest.raises(ConnectError):
        SystemConnector(root).disconnect("ghost")


# --- doctor integration -----------------------------------------------------

def test_doctor_flags_missing_mount_source(root, external):
    SystemConnector(root).connect(external, system_id="myproject")
    # remove the external source -> doctor mount check should fail
    (external / "readme.txt").unlink()
    external.rmdir()
    report = run_doctor(root)
    mount_check = next(c for c in report.checks if c.name == "mount: myproject")
    assert mount_check.ok is False


def test_doctor_notices_bare_folder(root):
    (root / "systems" / "barefolder").mkdir()
    report = run_doctor(root)
    assert any("barefolder" in n for n in report.notices)


# --- CLI --------------------------------------------------------------------

@pytest.fixture
def ammo_root(root, monkeypatch):
    monkeypatch.setenv("AMMO_ROOT", str(root))
    return root


def test_cli_connect_list_disconnect(ammo_root, external, capsys):
    assert cli.main(["connect", str(external), "--id", "proj", "--writable"]) == 0
    assert "Connected system pack" in capsys.readouterr().out

    assert cli.main(["list-systems"]) == 0
    assert "proj" in capsys.readouterr().out

    assert cli.main(["disconnect", "proj"]) == 0
    out = capsys.readouterr().out
    assert "Disconnected" in out
    assert (external / "readme.txt").is_file()


def test_cli_connect_bad_path_exits_one(ammo_root, external, capsys):
    code = cli.main(["connect", str(external.parent / "missing"), "--id", "x", "--read-only"])
    out = capsys.readouterr().out
    assert code == 1 and "Error:" in out


# --- interactive access prompt ---------------------------------------------

def test_cli_connect_prompts_for_access_read_write(ammo_root, external, monkeypatch, capsys):
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda *a, **k: "w")
    assert cli.main(["connect", str(external), "--id", "proj"]) == 0
    assert "access: read-write" in capsys.readouterr().out
    pack = SystemPackLoader(ammo_root).load("proj")
    assert pack.manifest["writable"] is True


def test_cli_connect_prompts_for_access_read_only(ammo_root, external, monkeypatch, capsys):
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda *a, **k: "r")
    assert cli.main(["connect", str(external), "--id", "proj"]) == 0
    assert "access: read-only" in capsys.readouterr().out
    pack = SystemPackLoader(ammo_root).load("proj")
    assert pack.manifest["writable"] is False


def test_cli_connect_non_tty_without_flag_errors(ammo_root, external, monkeypatch, capsys):
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
    code = cli.main(["connect", str(external), "--id", "proj"])
    out = capsys.readouterr().out
    assert code == 2
    assert "--read-only or --writable" in out
    assert not (ammo_root / "systems" / "proj").exists()  # nothing created


def test_cli_connect_conflicting_flags_errors(ammo_root, external, capsys):
    code = cli.main(["connect", str(external), "--id", "proj", "--read-only", "--writable"])
    out = capsys.readouterr().out
    assert code == 2 and "not both" in out


def test_connect_warns_on_nested_source(tmp_path, monkeypatch, capsys):
    import os, shutil
    root = tmp_path / "root"
    root.mkdir()
    os.symlink(REPO_ROOT / "registry", root / "registry")
    shutil.copytree(REPO_ROOT / "systems", root / "systems")
    for name in ("runtime", "memory", "vaults"):
        (root / name).mkdir()
    nested = root / "runtime" / "innerdir"
    nested.mkdir()
    monkeypatch.setenv("AMMO_ROOT", str(root))

    from ammo import cli

    code = cli.main(["connect", str(nested), "--read-only"])
    out = capsys.readouterr().out
    assert code == 0
    assert "INSIDE the AMMO root" in out            # warned, still proceeded
