"""Tests for real-usage parsing from provider CLI output (M: usage parsing).

Sample payloads are trimmed copies of REAL output captured live on 2026-07-02
(claude 2.1.198 `--output-format json`; codex-cli 0.139.0 `exec --json`).
"""

import json

from ammo.adapters import AdapterRequest, CommandAdapter
from ammo.adapters.usage_parsers import PARSERS, parse_claude_json, parse_codex_jsonl

CLAUDE_JSON = json.dumps({
    "type": "result", "subtype": "success", "is_error": False,
    "result": "OK",
    "usage": {
        "input_tokens": 3738, "output_tokens": 4,
        "cache_creation_input_tokens": 0, "cache_read_input_tokens": 18802,
        "service_tier": "standard",
    },
    "total_cost_usd": 0.056382,
})

CODEX_JSONL = "\n".join([
    '{"type":"thread.started","thread_id":"019f209b"}',
    '{"type":"turn.started"}',
    '{"type":"item.completed","item":{"id":"item_0","type":"agent_message","text":"OK"}}',
    '{"type":"turn.completed","usage":{"input_tokens":15158,"cached_input_tokens":10624,'
    '"output_tokens":20,"reasoning_output_tokens":13}}',
])


# --- claude json --------------------------------------------------------------

def test_claude_json_extracts_text_usage_and_cost():
    text, usage = parse_claude_json(CLAUDE_JSON)
    assert text == "OK"
    assert usage.estimated is False
    assert usage.input_tokens == 3738 + 18802  # uncached + cache reads + creations
    assert usage.output_tokens == 4
    assert usage.cost_usd == 0.056382


def test_claude_json_falls_back_on_garbage():
    text, usage = parse_claude_json("not json at all")
    assert text == "not json at all" and usage is None


def test_claude_json_falls_back_when_result_missing():
    text, usage = parse_claude_json(json.dumps({"usage": {"input_tokens": 1}}))
    assert usage is None  # no result field -> treat as unparsed


# --- codex jsonl ----------------------------------------------------------------

def test_codex_jsonl_extracts_text_and_usage():
    text, usage = parse_codex_jsonl(CODEX_JSONL)
    assert text == "OK"
    assert usage.estimated is False
    assert usage.input_tokens == 15158 and usage.output_tokens == 20
    assert usage.cost_usd is None  # codex reports tokens, not cost


def test_codex_jsonl_tolerates_noise_lines():
    noisy = "warning: something\n" + CODEX_JSONL + "\ntrailing garbage"
    text, usage = parse_codex_jsonl(noisy)
    assert text == "OK" and usage.input_tokens == 15158


def test_codex_jsonl_falls_back_on_garbage():
    text, usage = parse_codex_jsonl("plain text output")
    assert text == "plain text output" and usage is None


# --- CommandAdapter integration ----------------------------------------------

def _req():
    return AdapterRequest(role="planner", model="m", task_input="say ok")


def test_adapter_uses_parser_for_clean_text_and_real_usage():
    adapter = CommandAdapter("m", ["claude", "-p", "--output-format", "json"],
                             runner=lambda cmd, stdin="": (0, CLAUDE_JSON),
                             parser=PARSERS["claude_json"])
    resp = adapter.execute(_req())
    assert resp.output == "OK"                      # clean text, not raw JSON
    assert resp.usage.estimated is False            # REAL usage
    assert resp.usage.cost_usd == 0.056382


def test_adapter_falls_back_to_estimate_when_parse_fails():
    adapter = CommandAdapter("m", ["claude", "-p"],
                             runner=lambda cmd, stdin="": (0, "just plain text"),
                             parser=PARSERS["claude_json"])
    resp = adapter.execute(_req())
    assert resp.output == "just plain text"
    assert resp.usage.estimated is True             # graceful estimate fallback


def test_adapter_without_parser_still_estimates():
    adapter = CommandAdapter("m", ["x"], runner=lambda cmd, stdin="": (0, "hello"))
    resp = adapter.execute(_req())
    assert resp.usage.estimated is True


# --- resolver wiring -----------------------------------------------------------

def test_resolver_attaches_parser_from_profile():
    from ammo.adapters import RealAdapterFactory
    from ammo.providers import DEFAULT_CATALOG
    from ammo.providers.profile import ProviderStatus

    claude = next(p for p in DEFAULT_CATALOG if p.id == "claude-code")
    statuses = [ProviderStatus(claude, True, "authenticated", list(claude.models))]
    factory = RealAdapterFactory(statuses=statuses, runner=lambda c, stdin="": (0, CLAUDE_JSON))
    adapter = factory("claude_a_planner")
    assert adapter._parser is PARSERS["claude_json"]
    assert "--output-format" in adapter._command
    resp = adapter.execute(_req())
    assert resp.output == "OK" and resp.usage.estimated is False


# --- economics prefers reported cost ------------------------------------------

def test_run_economics_prefers_reported_cost():
    from ammo.adapters import AdapterResponse, Usage
    from ammo.economics import ModelPrice, PricingBook

    book = PricingBook({"m": ModelPrice("m", "subscription", 5.0, 25.0)})
    responses = [AdapterResponse(role="r", model="m", output="",
                                 usage=Usage(1000, 100, estimated=False, cost_usd=0.5))]
    econ = book.run_economics(responses)
    assert econ["estimated_cost"] == 0.5            # reported cost wins over book
