"""Tests for the model adapter contract and MockAdapter (Milestone 7)."""

import pytest

from ammo.adapters import (
    AdapterRequest,
    AdapterResponse,
    BaseModelAdapter,
    Evidence,
    MockAdapter,
    ToolRequest,
)

ROLES = ["planner", "builder", "critic", "researcher", "skeptic", "synthesizer", "judge", "fast_worker"]


def _req(role, task="do the thing"):
    return AdapterRequest(role=role, model="mock-x", task_input=task)


# --- contract ---------------------------------------------------------------

def test_base_adapter_is_abstract():
    with pytest.raises(TypeError):
        BaseModelAdapter("x")  # abstract methods not implemented


def test_dataclasses_to_dict():
    tr = ToolRequest("web.search", {"q": "x"}, "find")
    ev = Evidence("diff", "a diff", ok=True)
    assert tr.to_dict()["tool"] == "web.search"
    assert ev.to_dict()["ok"] is True
    resp = AdapterResponse(role="planner", model="m", output="o", confidence=0.5,
                           tool_requests=[tr], evidence=[ev])
    d = resp.to_dict()
    assert d["tool_requests"][0]["tool"] == "web.search"
    assert d["evidence"][0]["kind"] == "diff"


# --- MockAdapter ------------------------------------------------------------

def test_mock_adapter_is_a_base_adapter():
    a = MockAdapter("mock-x")
    assert isinstance(a, BaseModelAdapter)
    assert a.describe()["id"] == "mock-x"
    assert a.describe()["kind"] == "mock"


def test_mock_adapter_is_deterministic():
    a = MockAdapter("mock-x")
    r1 = a.execute(_req("planner"))
    r2 = a.execute(_req("planner"))
    assert r1.to_dict() == r2.to_dict()


@pytest.mark.parametrize("role", ROLES)
def test_every_role_produces_valid_output(role):
    resp = MockAdapter("mock-x").execute(_req(role))
    assert resp.role == role
    assert resp.output
    assert 0.0 <= resp.confidence <= 1.0
    assert all(isinstance(e, Evidence) for e in resp.evidence)


def test_roles_produce_distinct_outputs():
    outputs = {role: MockAdapter("m").execute(_req(role)).output for role in ROLES}
    assert len(set(outputs.values())) == len(ROLES)  # each role differs


def test_builder_and_researcher_declare_tools():
    builder = MockAdapter("m").execute(_req("builder"))
    assert {t.tool for t in builder.tool_requests} == {"fs.write", "git"}
    researcher = MockAdapter("m").execute(_req("researcher"))
    assert researcher.tool_requests[0].tool == "web.search"


def test_unknown_role_falls_back_generically():
    resp = MockAdapter("m").execute(_req("test_runner"))
    assert "test_runner" in resp.output
    assert resp.evidence
