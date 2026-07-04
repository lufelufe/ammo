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
    # deterministic + instant provider detection (no live `claude auth status`
    # subprocesses), so the gate tests don't flake on real auth timing.
    env = dict(os.environ, AMMO_ROOT=str(root),
               AMMO_FAKE_READY_PROVIDERS="claude-code,claude-code-b,codex")
    child = pexpect.spawn(PYTHON, ["-m", "ammo", *argv], env=env,
                          encoding="utf-8", timeout=timeout)
    return child


def test_first_summon_wizard_interactive(root):
    child = _spawn(root, "start", "--host", "terminal", timeout=90)
    child.expect(r"first summon setup")
    child.expect(r"\[1/5\] Host: terminal")
    # a usable model was detected on this machine -> primary confirm prompt
    child.expect(r"Use it as the primary model\? \[Y/n\]")
    child.sendline("y")
    child.expect(r"\[2/5\] Usable models:")
    child.expect(r"preferred set\?")
    child.sendline("claude_a_opus")               # narrow the set by typing ids
    child.expect(r"\[3/5\] Default objective")
    child.sendline("cost")
    child.expect(r"Saved ammo\.config\.yaml")
    # [4/5] the engine -> model -> role gates open inline
    child.expect(r"\[4/5\] Team roles")
    child.expect(r"Gate 1")                       # engine gate
    child.sendline("1")                           # first ready engine
    child.expect(r"Gate 2")                       # its models
    child.sendline("1")                           # first model
    child.expect(r"Gate 3")                       # role for that engine·model
    child.sendline("1")                           # orchestrator
    child.expect(r"Gate 1")                       # loops back = member seated
    child.sendline("done")
    # [5/5] workspace directory gate — skip here
    child.expect(r"\[5/5\] Workspace")
    child.expect(r"path to connect")
    child.sendline("done")
    child.expect(r"ready")
    child.expect(pexpect.EOF)
    child.close()
    assert child.exitstatus == 0

    config = yaml.safe_load((root / "ammo.config.yaml").read_text(encoding="utf-8"))
    assert config["models"] == ["claude_a_opus"]  # the typed answer stuck
    assert config["default_objective"] == "cost"
    assert config.get("roles", {}).get("orchestrator")   # a member was seated via gates


def test_first_summon_workspace_connects_multiple_directories(root, tmp_path):
    """The [5/5] workspace gate loops to connect more than one directory."""
    work = tmp_path / "myproject"
    work.mkdir()
    (work / "node_modules").mkdir()               # a noise dir → recommended excl.
    work2 = tmp_path / "otherproject"
    work2.mkdir()
    child = _spawn(root, "start", "--host", "terminal", timeout=90)
    child.expect(r"Use it as the primary model\? \[Y/n\]")
    child.sendline("y")
    child.expect(r"preferred set\?")
    child.sendline("y")
    child.expect(r"\[3/5\] Default objective")
    child.sendline("")
    child.expect(r"\[4/5\] Team roles")
    child.expect(r"Gate 1")
    child.sendline("done")                        # skip roles for this test
    child.expect(r"\[5/5\] Workspace")
    # first directory
    child.expect(r"path to connect")
    child.sendline(str(work))
    child.expect(r"read-\[w\]rite\? \[r/w\]")
    child.sendline("r")
    child.expect(r"Exclude sensitive")            # .ammoignore gate
    child.sendline("y")
    child.expect(r"excluding")
    # loop → second directory
    child.expect(r"path to connect")
    child.sendline(str(work2))
    child.expect(r"read-\[w\]rite\? \[r/w\]")
    child.sendline("w")
    child.expect(r"Exclude sensitive")
    child.sendline("n")                           # keep default for the second
    child.expect(r"path to connect")
    child.sendline("done")
    child.expect(r"ready")
    child.expect(pexpect.EOF)
    child.close()
    assert child.exitstatus == 0

    m1 = yaml.safe_load(
        (root / "systems" / "myproject" / ".ammo" / "manifest.yaml").read_text(encoding="utf-8"))
    m2 = yaml.safe_load(
        (root / "systems" / "otherproject" / ".ammo" / "manifest.yaml").read_text(encoding="utf-8"))
    assert m1["source_path"] == str(work) and m1["writable"] is False   # 'r'
    assert m2["source_path"] == str(work2) and m2["writable"] is True    # 'w'
    ignore = (root / "systems" / "myproject" / ".ammoignore").read_text(encoding="utf-8")
    assert ".env" in ignore and "node_modules/" in ignore


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
