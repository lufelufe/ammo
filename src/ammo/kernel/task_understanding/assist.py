"""Model-assisted task understanding (P4) — rules first, a model fills gaps.

Policy: the rule engine stays the router of record. Only when it is UNCERTAIN
(domain None/"general") do we ask a cheap model to classify the request into
the same schema; a valid answer becomes a *hint* re-fed through the rule
pipeline (so candidate systems, tools, and tags derive consistently). A
confident rule verdict is never overridden. Never raises; on any garbage the
rules verdict stands.
"""

from __future__ import annotations

import json
import re
from typing import Callable, Optional

VALID_DOMAINS = {"personal", "research", "coding", "ops", "investment", "general"}

CLASSIFY_PROMPT = (
    "Classify this request. Reply with ONLY a JSON object, no prose:\n"
    '{"domain": one of ["personal","research","coding","ops","investment","general"], '
    '"intent": "short_snake_case", "risk": one of ["low","medium","high"]}\n\n'
    "Request: {raw}"
)

_JSON_RE = re.compile(r"\{.*?\}", re.S)


def classify(raw_input: str, invoke: Callable[[str], str]) -> Optional[dict]:
    """Ask the model; return a validated dict or None (never raises)."""
    try:
        output = invoke(CLASSIFY_PROMPT.replace("{raw}", raw_input)) or ""
        match = _JSON_RE.search(output)
        if not match:
            return None
        data = json.loads(match.group(0))
    except Exception:
        return None
    domain = str(data.get("domain") or "").lower()
    if domain not in VALID_DOMAINS:
        return None
    intent = re.sub(r"[^a-z0-9_]", "", str(data.get("intent") or "").lower()) or None
    risk = str(data.get("risk") or "").lower()
    return {"domain": domain, "intent": intent,
            "risk": risk if risk in {"low", "medium", "high"} else None}


def assisted_analyze(analyzer, raw_input: str, invoke: Callable[[str], str]):
    """Rules-first analysis with a model filling only the uncertain gaps."""
    rules = analyzer.analyze(raw_input)
    if rules.domain not in (None, "general"):
        return rules                      # confident rules: no model call at all
    assist = classify(raw_input, invoke)
    if not assist or assist["domain"] in (None, "general"):
        return rules                      # model didn't help; rules stand
    return analyzer.analyze(raw_input, domain_hint=assist["domain"],
                            intent_hint=assist["intent"])
