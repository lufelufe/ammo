"""UI tests — drive the real CLI in a pseudo-terminal (pexpect).

capsys tests assert *content*; these assert the interactive UX itself: the
prompts appear, answers steer the flow, and the outcome matches what the user
chose. They spawn `python -m ammo` under a PTY, exactly like a human terminal.
"""

import json
import os
import shutil
import sys
from pathlib import Path

import pexpect
import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
PYTHON = sys.executable


@pytest.fixture
def root(tmp_path):
    r = tmp_path / "root"
    r.mkdir()
    os.symlink(REPO_ROOT / "registry", r / "registry")
    shutil.copytree(REPO_ROOT / "systems", r / "systems")
    for name in ("runtime", "memory", "vaults"):
        (r / name).mkdir()
    return r


def _spawn(root, *argv, timeout=45):
    env = dict(os.environ, AMMO_ROOT=str(root))
    child = pexpect.spawn(PYTHON, ["-m", "ammo", *argv], env=env,
                          encoding="utf-8", timeout=timeout)
    return child


def test_first_summon_wizard_interactive(root):
    child = _spawn(root, "start", "--host", "terminal")
    child.expect(r"first summon setup")
    child.expect(r"\[1/4\] Host: terminal")
    # a usable model was detected on this machine -> primary confirm prompt
    child.expect(r"Use it as the primary model\? \[Y/n\]")
    child.sendline("y")
    child.expect(r"\[2/4\] Usable models:")
    child.expect(r"preferred set\?")
    child.sendline("claude_a_opus")               # narrow the set by typing ids
    child.expect(r"\[3/4\] Workspace")
    child.expect(r"\[4/4\] Default objective")
    child.sendline("cost")
    child.expect(r"Saved ammo\.config\.yaml")
    child.expect(r"ready")
    child.expect(pexpect.EOF)
    child.close()
    assert child.exitstatus == 0

    config = yaml.safe_load((root / "ammo.config.yaml").read_text(encoding="utf-8"))
    assert config["models"] == ["claude_a_opus"]  # the typed answer stuck
    assert config["default_objective"] == "cost"


def test_repeat_summon_skips_the_wizard(root):
    first = _spawn(root, "start", "--host", "terminal", "--yes")
    first.expect(pexpect.EOF)
    first.close()

    child = _spawn(root, "start")
    index = child.expect([r"first summon setup", r"ready"])
    assert index == 1                                 # straight to the summary
    child.expect(pexpect.EOF)
    child.close()
    assert child.exitstatus == 0


def test_connect_asks_for_access_and_honors_read_only(root, tmp_path):
    source = tmp_path / "mydir"
    source.mkdir()
    child = _spawn(root, "connect", str(source))
    child.expect(r"\[r\]ead-only or read-\[w\]rite\? \[r/w\]")
    child.sendline("r")
    child.expect(r"access: read-only")
    child.expect(pexpect.EOF)
    child.close()
    assert child.exitstatus == 0

    manifest = yaml.safe_load(
        (root / "systems" / "mydir" / ".ammo" / "manifest.yaml").read_text(encoding="utf-8")
    )
    assert manifest["writable"] is False              # the answer became policy


def test_help_lists_every_command(root):
    """UI surface regression net: every registered command shows in --help."""
    from ammo.cli import build_parser

    child = _spawn(root, "--help", timeout=15)
    child.expect(pexpect.EOF)
    out = child.before
    child.close()

    sub = next(a for a in build_parser()._actions
               if a.__class__.__name__ == "_SubParsersAction")
    for command in sub.choices:
        assert command in out, f"--help is missing command: {command}"


def test_repo_root_launcher_works_without_venv_activation(root):
    """`./ammo` from a bare shell (Q2: summon from a plain terminal)."""
    import subprocess

    proc = subprocess.run([str(REPO_ROOT / "ammo"), "version"],
                          capture_output=True, text=True,
                          env={**os.environ, "AMMO_ROOT": str(root)}, timeout=30)
    assert proc.returncode == 0
    assert proc.stdout.startswith("ammo ")
