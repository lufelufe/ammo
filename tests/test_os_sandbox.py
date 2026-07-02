"""Tests for OS-level isolation (macOS seatbelt) of the sandbox.

Unit tests run everywhere; behavioral tests execute real kernel-confined
commands and are gated on seatbelt availability (macOS with sandbox-exec).
"""

import sys
import uuid
from pathlib import Path

import pytest

from ammo.tools.os_sandbox import (
    SEATBELT,
    detect_isolation,
    seatbelt_profile,
    wrap_command,
)
from ammo.tools.sandbox import Sandbox, SandboxError

HAVE_SEATBELT = detect_isolation() == SEATBELT


# --- unit (platform-independent) -------------------------------------------------

def test_detection_is_platform_and_binary_gated():
    assert detect_isolation(which=lambda c: "/usr/bin/sandbox-exec",
                            platform="darwin") == SEATBELT
    assert detect_isolation(which=lambda c: None, platform="darwin") is None
    only_seatbelt = lambda c: "/usr/bin/sandbox-exec" if c == "sandbox-exec" else None
    assert detect_isolation(which=only_seatbelt, platform="linux") is None


def test_profile_confines_writes_and_denies_network(tmp_path):
    profile = seatbelt_profile(tmp_path)
    assert "(deny network*)" in profile
    assert "(deny file-write*)" in profile
    assert f'(allow file-write* (subpath "{tmp_path.resolve()}"))' in profile
    # order matters in SBPL (last match wins): allow must come after deny
    assert profile.index("(deny file-write*)") < profile.index("(allow file-write*")


def test_profile_refuses_quoted_paths(tmp_path):
    evil = tmp_path / 'has"quote'
    evil.mkdir()
    with pytest.raises(ValueError):
        seatbelt_profile(evil)


def test_wrap_command_shapes(tmp_path):
    wrapped = wrap_command(["git", "init"], tmp_path, SEATBELT)
    assert wrapped[:2] == ["sandbox-exec", "-p"] and wrapped[-2:] == ["git", "init"]
    assert wrap_command(["ls"], tmp_path, None) == ["ls"]


def test_escalation_denied_even_with_isolation(tmp_path):
    sb = Sandbox(tmp_path / "sb", isolation=SEATBELT)
    with pytest.raises(SandboxError, match="escalation"):
        sb.run(["sudo", "ls"])


def test_without_isolation_allowlist_still_rules(tmp_path):
    sb = Sandbox(tmp_path / "sb", isolation=None)
    with pytest.raises(SandboxError, match="allowlist"):
        sb.run(["git", "init"])


# --- behavioral (kernel-enforced; darwin + sandbox-exec only) ----------------------

pytestmark_behavioral = pytest.mark.skipif(
    not HAVE_SEATBELT, reason="seatbelt (macOS sandbox-exec) not available")


@pytestmark_behavioral
def test_arbitrary_command_runs_inside(tmp_path):
    sb = Sandbox(tmp_path / "sb")            # auto -> seatbelt on this machine
    assert sb.isolation == SEATBELT
    code, _ = sb.run(["touch", "inside.txt"])   # touch is NOT in the allowlist
    assert code == 0
    assert (sb.dir / "inside.txt").is_file()


@pytestmark_behavioral
def test_write_escape_is_kernel_denied(tmp_path):
    sb = Sandbox(tmp_path / "sb")
    target = Path.home() / f".ammo_escape_{uuid.uuid4().hex[:8]}"
    try:
        code, out = sb.run(["touch", str(target)])
        assert code != 0
        assert "not permitted" in out.lower()
        assert not target.exists()               # the kernel said no
    finally:
        target.unlink(missing_ok=True)


@pytestmark_behavioral
def test_network_is_kernel_denied(tmp_path):
    sb = Sandbox(tmp_path / "sb")
    code, out = sb.run([
        "python3", "-c",
        "import socket; socket.create_connection(('1.1.1.1', 53), timeout=2)",
    ])
    assert code != 0
    assert "not permitted" in out.lower() or "PermissionError" in out


@pytestmark_behavioral
def test_git_works_confined(tmp_path):
    sb = Sandbox(tmp_path / "sb")
    code, out = sb.run(["git", "init", "-q", "."])
    assert code == 0, out
    assert (sb.dir / ".git").is_dir()
    (sb.dir / "a.txt").write_text("hello", encoding="utf-8")
    code, out = sb.run(["git", "add", "a.txt"])
    assert code == 0, out


@pytestmark_behavioral
def test_executor_shell_runs_git_under_isolation(tmp_path):
    """End-to-end: a worker's shell.run git request executes kernel-confined."""
    from ammo.adapters.contract import ToolRequest
    from ammo.tools import PermissionGate, ToolExecutor

    gate = PermissionGate(tmp_path, read_scopes=[], write_scopes=["sb"],
                          network=False, allowed_tools=["shell.run"], ammoignore=[])
    executor = ToolExecutor(gate, sandbox=Sandbox(tmp_path / "sb"))
    (evidence,) = executor.run_all([ToolRequest(tool="shell.run",
                                                args={"cmd": "git init -q ."},
                                                reason="init repo")])
    assert evidence.ok, evidence.detail
    assert (tmp_path / "sb" / ".git").is_dir()


# --- linux (bwrap) — unit-level only; behavioral verification needs a Linux box

def test_bwrap_detection():
    assert detect_isolation(which=lambda c: "/usr/bin/bwrap",
                            platform="linux") == "bwrap"
    assert detect_isolation(which=lambda c: None, platform="linux") is None


def test_bwrap_wrap_shape(tmp_path):
    wrapped = wrap_command(["git", "init"], tmp_path, "bwrap")
    assert wrapped[0] == "bwrap"
    assert "--unshare-net" in wrapped                 # network denied
    joined = " ".join(wrapped)
    assert f"--bind {tmp_path.resolve()} {tmp_path.resolve()}" in joined
    assert wrapped[-2:] == ["git", "init"]
    assert wrapped.index("--ro-bind") < wrapped.index("--bind")  # root ro, sandbox rw
