"""Parse REAL usage (and clean text) from provider CLI output.

Shapes verified live on 2026-07-02:

- ``claude -p --output-format json`` → one JSON object with ``result`` (final
  text), ``usage.input_tokens/output_tokens`` (+cache fields), and
  ``total_cost_usd`` (real reported cost).
- ``codex exec --json`` → JSONL events; ``item.completed`` with
  ``item.type == "agent_message"`` carries the text, ``turn.completed`` carries
  ``usage.input_tokens/output_tokens``.

Every parser returns ``(text, usage_or_none)`` and must NEVER raise — on any
unexpected shape it returns the raw stdout with ``None`` so the caller falls
back to the chars/4 estimate.
"""

from __future__ import annotations

import json
from typing import Callable, Dict, Optional, Tuple

from ammo.adapters.contract import Usage

Parser = Callable[[str], Tuple[str, Optional[Usage]]]


def parse_claude_json(stdout: str) -> Tuple[str, Optional[Usage]]:
    try:
        data = json.loads(stdout)
        usage = data.get("usage") or {}
        parsed = Usage(
            input_tokens=int(usage.get("input_tokens") or 0)
            + int(usage.get("cache_read_input_tokens") or 0)
            + int(usage.get("cache_creation_input_tokens") or 0),
            output_tokens=int(usage.get("output_tokens") or 0),
            estimated=False,
            cost_usd=data.get("total_cost_usd"),
        )
        text = data.get("result")
        if text is None:
            return stdout, None
        return str(text), parsed
    except (json.JSONDecodeError, TypeError, ValueError, AttributeError):
        return stdout, None


def parse_codex_jsonl(stdout: str) -> Tuple[str, Optional[Usage]]:
    text: Optional[str] = None
    usage: Optional[Usage] = None
    try:
        for line in stdout.splitlines():
            line = line.strip()
            if not line.startswith("{"):
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if event.get("type") == "item.completed":
                item = event.get("item") or {}
                if item.get("type") == "agent_message" and item.get("text") is not None:
                    text = str(item["text"])
            elif event.get("type") == "turn.completed":
                u = event.get("usage") or {}
                usage = Usage(
                    input_tokens=int(u.get("input_tokens") or 0),
                    output_tokens=int(u.get("output_tokens") or 0),
                    estimated=False,
                )
    except (TypeError, ValueError, AttributeError):
        return stdout, None
    if text is None:
        return stdout, usage
    return text, usage


PARSERS: Dict[str, Parser] = {
    "claude_json": parse_claude_json,
    "codex_jsonl": parse_codex_jsonl,
}
