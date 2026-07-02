"""Task Understanding Engine v0 — rule-based, model-free.

Turns a raw request into a :class:`TaskVector`. It scores domains from bilingual
lexicons, derives intent/risk/needs from rules, and resolves candidate systems
against the packs' routing metadata (when an AMMO root is available). No model
is ever called.
"""

from __future__ import annotations

from typing import Dict, List, Optional

from ammo.kernel.task_understanding import signals as sg
from ammo.kernel.task_understanding.task_vector import TaskVector

# domain -> system pack ids that can serve it (investment is served by personal).
DOMAIN_TO_SYSTEMS: Dict[str, List[str]] = {
    "coding": ["coding"],
    "research": ["research"],
    "ops": ["ops"],
    "personal": ["personal"],
    "investment": ["personal"],
    "writing": [],
    "general": [],
}

# tie-break order when domain scores are equal (most specific first).
DOMAIN_PRIORITY = ["coding", "investment", "ops", "research", "writing", "personal"]

OUTPUT_TYPE = {
    "coding": "code_change",
    "research": "report",
    "investment": "briefing",
    "personal": "briefing",
    "ops": "action",
    "writing": "text",
    "general": "answer",
}

_DOMAIN_LEXICONS = {
    "coding": sg.CODING,
    "research": sg.RESEARCH,
    "investment": sg.INVESTMENT,
    "personal": sg.PERSONAL,
    "ops": sg.OPS,
    "writing": sg.WRITING,
}

# canonical ordering for required_tools output (ids exist in registry/tools.yaml)
_TOOL_ORDER = ["web.search", "web.fetch", "doc.read", "fs.read", "fs.write", "shell.run", "git", "cron"]


def _load_systems_routing() -> List[dict]:
    """Best-effort load of pack routing metadata; [] if unavailable/invalid."""
    try:
        from ammo.paths import find_ammo_root
        from ammo.registry import SystemPackLoader

        packs = SystemPackLoader(find_ammo_root()).load_all()
    except Exception:
        return []
    routing = []
    for pack in packs:
        match = pack.routing.get("match") or {}
        routing.append(
            {
                "id": pack.id,
                "priority": pack.routing.get("priority", 0),
                "keywords": match.get("keywords") or [],
                "intents": match.get("intents") or [],
            }
        )
    return routing


class TaskAnalyzer:
    """Rule-based task understanding. Deterministic and model-free."""

    def __init__(self, systems: Optional[List[dict]] = None):
        # `systems` is pack routing metadata; None => best-effort load.
        self.systems = systems if systems is not None else _load_systems_routing()

    # -- public -------------------------------------------------------------

    def analyze(self, raw_input: str, domain_hint: str = None,
                intent_hint: str = None) -> TaskVector:
        """`domain_hint`/`intent_hint` (from model-assisted understanding) are
        applied ONLY when the rule engine is uncertain (general/None) — rules
        stay the router of record when they are confident."""
        text = raw_input.lower()

        domain = self._domain(text)
        intent = self._intent(domain, text)
        hinted = False
        if domain in (None, "general") and domain_hint and domain_hint != domain:
            domain = domain_hint
            intent = intent_hint or self._intent(domain, text)
            hinted = True

        needs_current_info = sg.contains(text, sg.CURRENT_INFO)
        needs_tests = sg.contains(text, sg.TESTS)
        needs_code_execution = domain == "coding" or sg.contains(text, sg.CODE_EXECUTION)

        vector = TaskVector(
            raw_input=raw_input,
            domain=domain,
            intent=intent,
            risk=self._risk(domain, intent, text),
            context_size=self._context_size(text),
            output_type=OUTPUT_TYPE.get(domain, "answer"),
            privacy_level=self._privacy(domain, text),
            needs_current_info=needs_current_info,
            needs_code_execution=needs_code_execution,
            needs_tests=needs_tests,
        )
        vector.complexity = self._complexity(vector, text)
        vector.required_tools = self._tools(vector, text)
        vector.candidate_systems = self._candidate_systems(domain, text)
        vector.tags = self._tags(vector, text)
        if hinted:
            vector.understanding_source = "rules+assist"
        return vector

    # -- classification steps ----------------------------------------------

    def _domain(self, text: str) -> str:
        scores = {d: sg.count(text, terms) for d, terms in _DOMAIN_LEXICONS.items()}
        best = max(scores.values())
        if best == 0:
            return "general"
        # highest score, tie-broken by DOMAIN_PRIORITY
        return min(
            (d for d, s in scores.items() if s == best),
            key=lambda d: DOMAIN_PRIORITY.index(d),
        )

    def _intent(self, domain: str, text: str) -> str:
        if domain == "coding":
            if sg.contains(text, sg.REVIEW):
                return "code_review"
            if sg.contains(text, sg.DEBUG):
                return "debug_and_patch"
            if sg.contains(text, sg.REFACTOR):
                return "refactor"
            if sg.contains(text, sg.EXPLAIN):
                return "explain"
            if sg.contains(text, sg.IMPLEMENT):
                return "implement"
            return "coding_task"
        if domain == "research":
            if sg.contains(text, sg.VERIFY):
                return "verify"
            if sg.contains(text, sg.LITERATURE):
                return "literature_scan"
            if sg.contains(text, sg.SYNTHESIZE):
                return "synthesize"
            return "research_investigation"
        if domain == "investment":
            return "investment_intel"
        if domain == "ops":
            if sg.contains(text, sg.SCHEDULE):
                return "schedule"
            if sg.contains(text, sg.DEPLOY):
                return "deploy"
            if sg.contains(text, sg.MONITOR):
                return "monitor"
            return "ops_task"
        if domain == "personal":
            if sg.contains(text, sg.BRIEFING):
                return "briefing"
            return "personal_task"
        if domain == "writing":
            return "compose"
        return "answer"

    def _risk(self, domain: str, intent: str, text: str) -> str:
        if sg.contains(text, sg.DESTRUCTIVE):
            return "high"
        if domain == "coding" and intent in {"debug_and_patch", "implement", "refactor"}:
            return "high"
        if sg.contains(text, sg.MONEY_MOVE):
            return "high"

        medium = (
            domain == "ops"
            or (domain == "coding" and intent == "code_review")
            or (domain == "investment" and sg.contains(text, sg.DECISION))
            or sg.contains(text, sg.SEND_WRITE)
        )
        return "medium" if medium else "low"

    def _context_size(self, text: str) -> str:
        scope = sg.contains(
            text,
            ["전체", "모든", "codebase", "코드베이스", "repository", "entire", "whole", "all files", "대규모"],
        )
        words = len(text.split())
        if scope or words > 40:
            return "large"
        if words <= 8:
            return "small"
        return "medium"

    def _complexity(self, vector: TaskVector, text: str) -> str:
        conjunctions = sg.count(text, ["그리고", "이랑", "랑", "및", "하고", "그다음", "and", "then", ",", "+"])
        if (vector.domain == "coding" and vector.needs_tests) or conjunctions >= 2:
            return "high"
        if conjunctions == 1 or vector.needs_tests or vector.domain in {"research", "coding"}:
            return "medium"
        return "low"

    def _privacy(self, domain: str, text: str) -> str:
        if sg.contains(text, ["비밀", "secret", "private", "vault", "비공개", "password", "credential", "개인정보"]):
            return "private"
        if domain in {"personal", "investment"} or sg.contains(
            text, ["나의", "내 ", "할일", "할 일", "일정", "캘린더", "개인", "my "]
        ):
            return "personal"
        return "public"

    def _tools(self, vector: TaskVector, text: str) -> List[str]:
        tools = set()
        if vector.needs_current_info:
            tools.update(["web.search", "web.fetch"])
        if vector.domain == "coding":
            tools.update(["fs.read", "fs.write", "git"])
        if vector.needs_code_execution:
            tools.add("shell.run")
        if vector.domain == "research":
            tools.update(["web.search", "web.fetch", "doc.read"])
        if vector.domain == "ops":
            tools.add("shell.run")
            if vector.intent == "schedule":
                tools.add("cron")
        return [t for t in _TOOL_ORDER if t in tools]

    def _candidate_systems(self, domain: str, text: str) -> List[str]:
        base = list(DOMAIN_TO_SYSTEMS.get(domain, []))
        if not self.systems:
            return base

        known = {s["id"]: s for s in self.systems}
        present = [sid for sid in base if sid in known]
        if present:
            present.sort(key=lambda sid: known[sid].get("priority", 0), reverse=True)
            return present

        # general/unknown: fall back to packs whose routing keywords match.
        matched = [s for s in self.systems if sg.contains(text, s.get("keywords", []))]
        matched.sort(key=lambda s: s.get("priority", 0), reverse=True)
        return [s["id"] for s in matched]

    def _tags(self, vector: TaskVector, text: str) -> List[str]:
        tags: List[str] = []

        for tag, terms in sg.LANGUAGES:
            if sg.contains(text, terms) and tag not in tags:
                tags.append(tag)

        if vector.intent == "debug_and_patch" or sg.contains(text, sg.DEBUG):
            tags.append("debugging")
        if vector.needs_tests:
            tags.append("tests_required")
        if vector.domain == "investment":
            tags.append("investment")
        if sg.contains(text, ["부동산", "real estate", "real-estate"]):
            tags.append("real_estate")
        if vector.domain == "research":
            tags.append("research")
        if vector.needs_current_info and sg.contains(text, ["뉴스", "news"]):
            tags.append("news")
        if vector.intent == "schedule":
            tags.append("scheduling")
        if sg.contains(text, sg.DEPLOY):
            tags.append("deployment")
        if vector.domain == "writing":
            tags.append("writing")
        if vector.intent == "briefing":
            tags.append("briefing")

        # de-duplicate, preserve order
        seen = set()
        return [t for t in tags if not (t in seen or seen.add(t))]


def analyze(raw_input: str, systems: Optional[List[dict]] = None) -> TaskVector:
    """Convenience wrapper: analyze a single request."""
    return TaskAnalyzer(systems=systems).analyze(raw_input)
