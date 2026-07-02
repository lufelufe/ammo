"""Tests for the triage module — self-diagnosis with proposed fixes."""

import os
import shutil
import sqlite3
from pathlib import Path

import pytest
import yaml

from ammo import cli
from ammo.adapters import AdapterResponse, Evidence, Usage
from ammo.registry import RegistryError
from ammo.triage import diagnose_exception, diagnose_run

REPO_ROOT = Path(__file__).resolve().parents[1]


# --- exception triage -------------------------------------------------------------

def test_missing_module_points_at_the_venv():
    d = diagnose_exception(ModuleNotFoundError("No module named 'yaml'"))
    assert "missing" in d.problem
    assert any(".venv" in f for f in d.fixes)


def test_yaml_error_family_is_recognized():
    try:
        yaml.safe_load("broken: [unclosed")
    except yaml.YAMLError as exc:
        d = diagnose_exception(exc)
    assert "YAML" in d.problem
    assert any("git checkout" in f for f in d.fixes)


def test_registry_error_subclass_hits_the_family_rule():
    class ValidationError(RegistryError):
        pass

    d = diagnose_exception(ValidationError("registry/systems.yaml: invalid YAML"))
    assert "validation" in d.problem
    assert any("doctor" in f for f in d.fixes)


def test_sqlite_error_suggests_the_dream_backup():
    d = diagnose_exception(sqlite3.OperationalError("database disk image is malformed"))
    assert any("ammo.sqlite.bak" in f for f in d.fixes)


def test_unknown_error_still_gets_a_card():
    d = diagnose_exception(RuntimeError("weird"))
    assert "unexpected error" in d.problem and "weird" in d.problem
    assert any("triage rule" in f for f in d.fixes)      # nothing swallowed silently


# --- run-signal triage --------------------------------------------------------------

def _resp(role, evidence=None, usage=None, model="m"):
    return AdapterResponse(role=role, model=model, output="out",
                           evidence=evidence or [], usage=usage)


def test_clean_run_yields_no_diagnoses():
    assert diagnose_run([_resp("a", [Evidence("plan", "ok", ok=True)])]) == []


def test_failed_invocation_diagnosis():
    bad = _resp("builder", [Evidence("invocation", "attempt 1 failed", ok=False)])
    (d,) = diagnose_run([bad])
    assert "invocation" in d.problem and "builder" in d.problem
    assert any("ammo providers" in f for f in d.fixes)


def test_denied_tool_diagnosis_names_the_permissions_file():
    denied = _resp("builder", [Evidence("tool", "fs.write denied", ok=False)])
    (d,) = diagnose_run([denied], system_id="coding")
    assert "fs.write denied" in d.problem
    assert any("systems/coding/.ammo/permissions.yaml" in f for f in d.fixes)


def test_unpriced_models_diagnosis():
    econ = {"unpriced_models": ["ghost_model"]}
    diagnoses = diagnose_run([_resp("a", [Evidence("x", "y", ok=True)])], economics=econ)
    assert any("ammo pricing set" in f for d in diagnoses for f in d.fixes)


def test_all_estimated_usage_in_real_mode_flags_parser_drift():
    responses = [_resp("a", [Evidence("x", "y", ok=True)],
                       usage=Usage(10, 5, estimated=True))]
    diagnoses = diagnose_run(responses, mode="real")
    assert any("usage_parsers" in f for d in diagnoses for f in d.fixes)
    # same responses in mock mode: estimates are expected, no diagnosis
    assert not any("usage_parsers" in f
                   for d in diagnose_run(responses, mode="mock") for f in d.fixes)


# --- CLI integration -----------------------------------------------------------------

@pytest.fixture
def ammo_root(tmp_path, monkeypatch):
    root = tmp_path / "root"
    root.mkdir()
    shutil.copytree(REPO_ROOT / "registry", root / "registry")
    shutil.copytree(REPO_ROOT / "systems", root / "systems")
    for name in ("runtime", "memory", "vaults"):
        (root / name).mkdir()
    monkeypatch.setenv("AMMO_ROOT", str(root))
    return root


def test_cli_broken_yaml_prints_diagnosis_not_traceback(ammo_root, capsys):
    with (ammo_root / "registry" / "systems.yaml").open("a", encoding="utf-8") as fh:
        fh.write("  broken: [unclosed\n")
    code = cli.main(["list-systems"])
    captured = capsys.readouterr()
    assert code == 1
    assert "self-diagnosis" in captured.err
    assert "Traceback" not in captured.err
    assert "git checkout" in captured.err


def test_cli_run_prints_tool_denial_diagnosis(ammo_root, capsys):
    code = cli.main(["run", "--mock", "이 python repo 버그 고쳐줘"])
    out = capsys.readouterr().out
    assert code == 0
    assert "self-diagnosis: tool(s) denied" in out
    assert "permissions.yaml" in out
