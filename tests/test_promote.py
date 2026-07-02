"""Tests for sandbox→real promotion (`ammo promote`)."""

import json
import os
import shutil
from pathlib import Path

import pytest

from ammo import cli
from ammo.connect import SystemConnector
from ammo.tools.promote import PromoteError, plan_promotion

REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def root(tmp_path):
    r = tmp_path / "root"
    r.mkdir()
    os.symlink(REPO_ROOT / "registry", r / "registry")
    shutil.copytree(REPO_ROOT / "systems", r / "systems")
    for name in ("runtime", "memory", "vaults"):
        (r / name).mkdir()
    (r / "runtime" / "runs").mkdir()
    return r


def _fake_run(root, run_id, system_id, sandbox_files, writable=True, source=None):
    """Create a connected system, a sandbox with files, and a run summary."""
    if source is None:
        source = root.parent / f"src_{system_id}"
        source.mkdir(exist_ok=True)
    SystemConnector(root).connect(source, system_id=system_id, writable=writable,
                                  tools=["fs.read", "fs.write"])
    sandbox = root / "runtime" / "sandbox" / run_id
    for rel, content in sandbox_files.items():
        p = sandbox / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
    run_dir = root / "runtime" / "runs" / run_id
    run_dir.mkdir(parents=True)
    (run_dir / "run_summary.json").write_text(json.dumps({
        "run_id": run_id, "selected_system": system_id, "sandbox": str(sandbox),
    }), encoding="utf-8")
    return source


def test_dry_run_shows_diff_without_touching_target(root):
    source = _fake_run(root, "r1", "proj", {"note.md": "sandbox version\n"})
    (source / "note.md").write_text("real version\n", encoding="utf-8")

    report = plan_promotion(root, "r1")
    assert report.applied is False
    (plan,) = report.files
    assert plan.status == "modified"
    assert "-real version" in plan.diff and "+sandbox version" in plan.diff
    assert (source / "note.md").read_text(encoding="utf-8") == "real version\n"


def test_apply_copies_and_backs_up(root):
    source = _fake_run(root, "r2", "proj2",
                       {"note.md": "sandbox version\n", "fresh.md": "brand new\n"})
    (source / "note.md").write_text("real version\n", encoding="utf-8")

    report = plan_promotion(root, "r2", apply=True)
    assert report.applied
    statuses = {f.relpath: f.status for f in report.files}
    assert statuses == {"note.md": "modified", "fresh.md": "new"}
    assert (source / "note.md").read_text(encoding="utf-8") == "sandbox version\n"
    assert (source / "fresh.md").read_text(encoding="utf-8") == "brand new\n"
    backup = root / "runtime" / "runs" / "r2" / "promote_backup" / "note.md"
    assert backup.read_text(encoding="utf-8") == "real version\n"   # pre-image kept


def test_unchanged_files_are_skipped(root):
    source = _fake_run(root, "r3", "proj3", {"same.md": "identical\n"})
    (source / "same.md").write_text("identical\n", encoding="utf-8")
    report = plan_promotion(root, "r3", apply=True)
    assert report.files[0].status == "unchanged"
    assert not (root / "runtime" / "runs" / "r3" / "promote_backup").exists()


def test_read_only_system_is_refused(root):
    _fake_run(root, "r4", "proj4", {"x.md": "content"}, writable=False)
    with pytest.raises(PromoteError, match="read-only"):
        plan_promotion(root, "r4")


def test_ammoignore_blocks_promotion_of_protected_paths(root):
    source = _fake_run(root, "r5", "proj5", {"secret.key": "boom", "ok.md": "fine"})
    ignore = root / "systems" / "proj5" / ".ammoignore"
    ignore.write_text("*.key\n", encoding="utf-8")

    report = plan_promotion(root, "r5", apply=True)
    statuses = {f.relpath: f.status for f in report.files}
    assert statuses["secret.key"] == "denied"
    assert statuses["ok.md"] == "new"
    assert not (source / "secret.key").exists()      # never written
    assert (source / "ok.md").is_file()


def test_missing_sandbox_is_a_clear_error(root):
    run_dir = root / "runtime" / "runs" / "r6"
    run_dir.mkdir(parents=True)
    (run_dir / "run_summary.json").write_text(json.dumps({
        "run_id": "r6", "selected_system": "coding", "sandbox": None,
    }), encoding="utf-8")
    with pytest.raises(PromoteError, match="no sandbox"):
        plan_promotion(root, "r6")


def test_cli_promote_dry_run_and_apply(root, monkeypatch, capsys):
    monkeypatch.setenv("AMMO_ROOT", str(root))
    source = _fake_run(root, "r7", "proj7", {"a.md": "v2\n"})
    (source / "a.md").write_text("v1\n", encoding="utf-8")

    assert cli.main(["promote", "r7"]) == 0
    out = capsys.readouterr().out
    assert "DRY-RUN" in out and "[modified] a.md" in out

    assert cli.main(["promote", "r7", "--apply"]) == 0
    assert "APPLIED" in capsys.readouterr().out
    assert (source / "a.md").read_text(encoding="utf-8") == "v2\n"

    assert cli.main(["promote", "nope"]) == 1        # unknown run -> clear error
