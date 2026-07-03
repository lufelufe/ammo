"""Tests for the interactive AMMO shell (ammo enter)."""

import pytest

from ammo.commands.shell import Session, run_shell


def _scripted(lines):
    """A read_line that yields scripted input then EOF (None)."""
    it = iter(lines)

    def read_line(prompt):
        return next(it, None)
    return read_line


def test_session_defaults_and_run_argv():
    s = Session()
    assert s.mode == "real"
    assert s.run_argv("hello") == ["run", "--real", "hello"]


def test_set_configures_defaults_applied_to_runs():
    s = Session()
    calls = []
    lines = ["set mock", "set optimize cost", "set show on",
             "set read docs AGENTS.md", "분석해줘", "exit"]
    run_shell(lambda argv: calls.append(argv), session=s, read_line=_scripted(lines))
    assert s.mode == "mock" and s.optimize == "cost" and s.show is True
    assert s.read == ["docs", "AGENTS.md"]
    # the bare request became a run with every session default applied
    assert calls == [["run", "--mock", "--optimize", "cost", "--show-confidence",
                      "--read", "docs", "AGENTS.md", "분석해줘"]]


def test_explicit_subcommand_runs_verbatim():
    calls = []
    run_shell(lambda argv: calls.append(argv), read_line=_scripted(["status", "exit"]))
    assert calls == [["status"]]                       # not wrapped in `run`


def test_feedback_subcommand_passes_through():
    calls = []
    run_shell(lambda argv: calls.append(argv),
              read_line=_scripted(["feedback r1 good", "exit"]))
    assert calls == [["feedback", "r1", "good"]]


def test_exit_variants_and_eof_leave():
    for terminator in (["exit"], ["/ammo exit"], ["quit"], [None]):
        code = run_shell(lambda argv: None, read_line=_scripted(terminator))
        assert code == 0


def test_blank_lines_and_help_do_not_dispatch():
    calls = []
    run_shell(lambda argv: calls.append(argv),
              read_line=_scripted(["", "  ", "help", "exit"]))
    assert calls == []                                 # nothing ran


def test_subcommand_arg_error_does_not_kill_the_shell():
    calls = []

    def dispatch(argv):
        calls.append(argv)
        if argv[0] == "show-run":
            raise SystemExit(2)                         # argparse-style failure
        return 0
    run_shell(dispatch, read_line=_scripted(["show-run", "다음 요청", "exit"]))
    # survived the SystemExit and processed the next line as a run
    assert calls[0] == ["show-run"]
    assert calls[1][0] == "run"


def test_set_read_with_no_path_clears_grounding():
    s = Session()
    s.read = ["docs"]
    run_shell(lambda argv: None, session=s, read_line=_scripted(["set read", "exit"]))
    assert s.read == []
