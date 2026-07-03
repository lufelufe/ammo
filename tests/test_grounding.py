"""Tests for P1 grounding — real files read into worker context before answering."""

from pathlib import Path

import pytest

from ammo.tools.grounding import gather

REPO_ROOT = Path(__file__).resolve().parents[1]


def _tree(tmp_path):
    (tmp_path / "docs").mkdir()
    (tmp_path / "a.md").write_text("# Alpha\nalpha body", encoding="utf-8")
    (tmp_path / "docs" / "guide.md").write_text("guide body", encoding="utf-8")
    (tmp_path / "code.py").write_text("print('hi')", encoding="utf-8")
    (tmp_path / "pic.png").write_bytes(b"\x89PNG binary")
    (tmp_path / "runtime").mkdir()
    (tmp_path / "runtime" / "noise.md").write_text("should be skipped", encoding="utf-8")
    return tmp_path


def test_reads_text_files_and_skips_binary_and_noise(tmp_path):
    root = _tree(tmp_path)
    g = gather(["."], root)
    assert "alpha body" in g.text and "guide body" in g.text and "print" in g.text
    assert "PNG binary" not in g.text                    # binary skipped
    assert "should be skipped" not in g.text             # runtime/ skipped
    assert set(g.files_read) >= {"a.md", "docs/guide.md", "code.py"}


def test_markdown_is_prioritized_over_code(tmp_path):
    root = _tree(tmp_path)
    g = gather(["."], root)
    assert g.files_read.index("a.md") < g.files_read.index("code.py")


def test_real_file_read_evidence(tmp_path):
    root = _tree(tmp_path)
    g = gather(["a.md"], root)
    ev = [e for e in g.evidence if e.kind == "file_read"]
    assert ev and ev[0].ok is True and "a.md" in ev[0].summary


def test_budget_bounds_and_flags_truncation(tmp_path):
    root = tmp_path
    (root / "big.md").write_text("x" * 50000, encoding="utf-8")
    g = gather(["."], root, budget=500)
    assert len(g.text) < 2000                            # header + capped snippet
    assert g.truncated is True


def test_permission_gate_denies_out_of_scope(tmp_path):
    from ammo.tools.permissions import PermissionGate

    root = _tree(tmp_path)
    # gate allows reads only under docs/
    gate = PermissionGate(root, read_scopes=["docs"], write_scopes=[],
                          network=False, allowed_tools=["fs.read"], ammoignore=[])
    g = gather(["."], root, gate=gate)
    assert "guide body" in g.text                        # docs/ allowed
    assert "alpha body" not in g.text                    # a.md denied
    assert any(not e.ok and "denied" in e.summary for e in g.evidence)


def test_empty_when_nothing_readable(tmp_path):
    (tmp_path / "pic.png").write_bytes(b"\x00")
    g = gather(["."], tmp_path)
    assert g.empty and g.files_read == []
