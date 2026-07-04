"""Tests for the paid-API HTTP route — fully offline via an injected transport.

Rule 4 is asserted structurally: the adapter object never holds the key; it is
read from the environment inside execute() and appears only in the outgoing
header the fake transport observes.
"""

import json

import pytest

from ammo.adapters import AdapterRequest, HttpAdapter, RealAdapterFactory
from ammo.providers import DEFAULT_CATALOG
from ammo.providers.profile import ProviderStatus

ANTHROPIC = next(p for p in DEFAULT_CATALOG if p.id == "anthropic-api")
OPENAI = next(p for p in DEFAULT_CATALOG if p.id == "openai-api")


def _req(model="claude_a_opus"):
    return AdapterRequest(role="planner", model=model, task_input="say ok")


class FakeTransport:
    def __init__(self, status=200, payload=None):
        self.status = status
        self.payload = payload
        self.calls = []

    def __call__(self, url, headers, body):
        self.calls.append({"url": url, "headers": headers, "body": body})
        return self.status, json.dumps(self.payload) if isinstance(self.payload, dict) else self.payload


ANTHROPIC_OK = {
    "content": [{"type": "text", "text": "OK from api"}],
    "usage": {"input_tokens": 12, "output_tokens": 3, "cache_read_input_tokens": 5},
}
OPENAI_OK = {
    "choices": [{"message": {"content": "OK from openai"}}],
    "usage": {"prompt_tokens": 20, "completion_tokens": 4},
}


def test_anthropic_request_shape_and_key_at_call_time(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-123")
    transport = FakeTransport(payload=ANTHROPIC_OK)
    adapter = HttpAdapter("claude_a_opus", ANTHROPIC, transport=transport)

    # rule 4: nothing secret on the object before/after the call
    assert "sk-test-123" not in repr(vars(adapter))
    response = adapter.execute(_req())

    call = transport.calls[0]
    assert call["url"].endswith("/v1/messages")
    assert call["headers"]["x-api-key"] == "sk-test-123"          # read at call time
    assert call["body"]["model"] == "claude-opus-4-8"             # node -> vendor name
    assert call["body"]["messages"][0]["role"] == "user"
    assert response.output == "OK from api"
    assert response.usage.estimated is False
    assert response.usage.input_tokens == 17                      # incl. cache reads
    assert "sk-test-123" not in repr(vars(adapter))


def test_openai_format(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-oa-9")
    transport = FakeTransport(payload=OPENAI_OK)
    adapter = HttpAdapter("codex_gpt5", OPENAI, transport=transport)
    response = adapter.execute(_req(model="codex_gpt5"))

    call = transport.calls[0]
    assert call["headers"]["authorization"] == "Bearer sk-oa-9"
    assert call["body"]["model"] == "gpt-5"
    assert response.output == "OK from openai"
    assert (response.usage.input_tokens, response.usage.output_tokens) == (20, 4)


def test_api_error_is_a_retryable_failure_marker():
    transport = FakeTransport(status=429, payload={"error": {"message": "rate limited"}})
    adapter = HttpAdapter("claude_a_opus", ANTHROPIC, transport=transport)
    response = adapter.execute(_req())
    assert response.output.startswith("(api error 429")
    assert response.usage is None

    from ammo.kernel.executor.runner import Runner
    assert Runner._failed(response) is True                       # retry hooks in


def test_unparseable_payload_is_reported():
    transport = FakeTransport(status=200, payload="not-json{")
    adapter = HttpAdapter("claude_a_opus", ANTHROPIC, transport=transport)
    assert adapter.execute(_req()).output.startswith("(api error: unparseable")


# --- resolver: the paid route engages only via allow_paid --------------------------

def _api_only_statuses():
    return [ProviderStatus(ANTHROPIC, True, "env var present", list(ANTHROPIC.models))]


def test_resolver_uses_http_route_when_paid_allowed(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    transport = FakeTransport(payload=ANTHROPIC_OK)
    factory = RealAdapterFactory(statuses=_api_only_statuses(), allow_paid=True,
                                 transport=transport)
    adapter = factory("claude_a_opus")
    assert isinstance(adapter, HttpAdapter)
    assert factory.resolutions["claude_a_opus"] == ("real", "anthropic-api")
    assert adapter.execute(_req()).output == "OK from api"


def test_resolver_stays_mock_without_allow_paid():
    factory = RealAdapterFactory(statuses=_api_only_statuses(), allow_paid=False)
    adapter = factory("claude_a_opus")
    assert not isinstance(adapter, HttpAdapter)
    assert factory.resolutions["claude_a_opus"][0] == "mock"


def test_no_extra_cost_route_still_wins_over_api(monkeypatch):
    """Subscription CLI and API both available -> the CLI (included) wins."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    claude_cli = next(p for p in DEFAULT_CATALOG if p.id == "claude-code")
    statuses = [
        ProviderStatus(claude_cli, True, "authenticated", list(claude_cli.models)),
        ProviderStatus(ANTHROPIC, True, "env var present", list(ANTHROPIC.models)),
    ]
    factory = RealAdapterFactory(statuses=statuses, allow_paid=True,
                                 runner=lambda c, stdin="": (0, "{}"))
    factory("claude_a_opus")
    assert factory.resolutions["claude_a_opus"] == ("real", "claude-code")
