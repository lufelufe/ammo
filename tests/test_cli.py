"""Tests for the Milestone 0 CLI placeholder.

These tests assert only what Milestone 0 promises: the CLI exists, exposes
``--help`` and ``--version``, and does no orchestration.
"""

import pytest

from ammo import __version__
from ammo import cli


def test_version_string_present():
    assert isinstance(__version__, str) and __version__


def test_build_parser_prog_name():
    parser = cli.build_parser()
    assert parser.prog == "ammo"


def test_help_exits_zero_and_mentions_kernel(capsys):
    with pytest.raises(SystemExit) as exc:
        cli.main(["--help"])
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "AMMO" in out
    # Philosophy must survive in the help epilog.
    assert "kernel" in out.lower()


def test_version_flag(capsys):
    with pytest.raises(SystemExit) as exc:
        cli.main(["--version"])
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert __version__ in out


def test_version_subcommand(capsys):
    code = cli.main(["version"])
    assert code == 0
    out = capsys.readouterr().out
    assert out.strip() == f"ammo {__version__}"


def test_no_args_prints_help_and_succeeds(capsys):
    code = cli.main([])
    assert code == 0
    out = capsys.readouterr().out
    assert "usage" in out.lower()
