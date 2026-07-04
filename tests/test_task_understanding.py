"""Tests for Task Understanding Engine v0 (Milestone 4).

Covers 18 bilingual sample prompts plus data-structure, convenience, routing,
and CLI checks. The big table uses ``TaskAnalyzer(systems=[])`` so results are
deterministic and independent of the on-disk packs.
"""

import json
from pathlib import Path

import pytest

from ammo import cli
from ammo.kernel.task_understanding import TaskAnalyzer, TaskVector, analyze
from ammo.kernel.task_understanding.analyzer import _load_systems_routing

REPO_ROOT = Path(__file__).resolve().parents[1]

# (prompt, expected field values, expected tag subset)
CASES = [
    # --- Korean ---
    (
        "이 Python repo 버그 고치고 테스트 추가해줘",
        {"domain": "coding", "intent": "debug_and_patch", "risk": "high",
         "needs_tests": True, "needs_code_execution": True, "candidate_systems": ["coding"]},
        ["python", "debugging", "tests_required"],
    ),
    (
        "오늘 투자 뉴스랑 할 일 정리해줘",
        {"domain": "personal", "needs_current_info": True, "candidate_systems": ["personal"]},
        ["news"],
    ),
    (
        "NVDA 주가랑 시장 상황 알려줘",
        {"domain": "investment", "intent": "investment_intel", "needs_current_info": True,
         "candidate_systems": ["personal"]},
        ["investment"],
    ),
    (
        "비트코인 시세 어때?",
        {"domain": "investment", "needs_current_info": True, "candidate_systems": ["personal"]},
        ["investment"],
    ),
    (
        "이 논문들 조사해서 근거랑 같이 정리해줘",
        {"domain": "research", "candidate_systems": ["research"], "output_type": "report"},
        ["research"],
    ),
    (
        "매일 아침 브리핑 스케줄 걸어줘",
        {"domain": "ops", "intent": "schedule", "candidate_systems": ["ops"]},
        ["scheduling"],
    ),
    (
        "서버 배포하고 상태 점검해줘",
        {"domain": "ops", "intent": "deploy", "risk": "high", "candidate_systems": ["ops"]},
        ["deployment"],
    ),
    (
        "이메일 초안 하나 써줘",
        {"domain": "writing", "intent": "compose", "risk": "low", "output_type": "text",
         "candidate_systems": []},
        ["writing"],
    ),
    (
        "부동산 이번 주 동향 요약해줘",
        {"domain": "investment", "needs_current_info": True, "candidate_systems": ["personal"]},
        ["real_estate"],
    ),
    (
        "이 함수 리팩터링 해줘",
        {"domain": "coding", "intent": "refactor", "risk": "high", "needs_code_execution": True,
         "candidate_systems": ["coding"]},
        [],
    ),
    # --- English ---
    (
        "Fix the failing tests in this Node.js project",
        {"domain": "coding", "intent": "debug_and_patch", "needs_tests": True,
         "candidate_systems": ["coding"]},
        ["javascript", "debugging", "tests_required"],
    ),
    (
        "Summarize the latest AI research papers with citations",
        {"domain": "research", "needs_current_info": True, "candidate_systems": ["research"]},
        ["research"],
    ),
    (
        "What's the current price of TSLA?",
        {"domain": "investment", "needs_current_info": True, "candidate_systems": ["personal"]},
        ["investment"],
    ),
    (
        "Write a blog post about my trip",
        {"domain": "writing", "intent": "compose", "privacy_level": "personal",
         "candidate_systems": []},
        ["writing"],
    ),
    (
        "Schedule a daily backup at 2am",
        {"domain": "ops", "intent": "schedule", "candidate_systems": ["ops"]},
        ["scheduling"],
    ),
    (
        "Review this pull request for bugs",
        {"domain": "coding", "intent": "code_review", "risk": "medium",
         "candidate_systems": ["coding"]},
        ["debugging"],
    ),
    (
        "What is the capital of France?",
        {"domain": "general", "intent": "answer", "risk": "low", "output_type": "answer",
         "candidate_systems": [], "needs_code_execution": False},
        [],
    ),
    (
        "이 코드베이스 전체 구조 설명해줘",
        {"domain": "coding", "intent": "explain", "risk": "low", "context_size": "large",
         "candidate_systems": ["coding"]},
        [],
    ),
]


@pytest.fixture(scope="module")
def analyzer():
    return TaskAnalyzer(systems=[])


@pytest.mark.parametrize("prompt,expected,tag_subset", CASES, ids=[c[0] for c in CASES])
def test_sample_prompts(analyzer, prompt, expected, tag_subset):
    vector = analyzer.analyze(prompt)
    for field, value in expected.items():
        assert getattr(vector, field) == value, (
            f"{field}: got {getattr(vector, field)!r}, expected {value!r} for {prompt!r}"
        )
    assert set(tag_subset).issubset(set(vector.tags)), (
        f"tags {vector.tags} missing {tag_subset} for {prompt!r}"
    )


def test_at_least_15_bilingual_cases():
    assert len(CASES) >= 15


# --- data structure & convenience ------------------------------------------

def test_task_vector_to_dict_field_order():
    keys = list(TaskVector(raw_input="x").to_dict().keys())
    assert keys[:4] == ["raw_input", "domain", "intent", "complexity"]
    assert "candidate_systems" in keys and "tags" in keys


def test_analyze_convenience_returns_vector():
    vector = analyze("fix a bug", systems=[])
    assert isinstance(vector, TaskVector)
    assert vector.domain == "coding"


def test_empty_input_is_general():
    vector = TaskAnalyzer(systems=[]).analyze("")
    assert vector.domain == "general"
    assert vector.required_tools == []
    assert vector.candidate_systems == []


def test_latest_does_not_trigger_tests():
    # word-boundary matching: "latest" must not fire the "test" signal.
    vector = TaskAnalyzer(systems=[]).analyze("show me the latest headlines")
    assert vector.needs_tests is False


def test_trivial_or_advisory_coding_change_is_not_high_risk():
    """A small-scope or advisory coding change routes to a lighter team, not the
    full high-risk one. Real changes and destructive ops stay high."""
    a = TaskAnalyzer(systems=[])
    # trivial + advisory
    assert a.analyze("pyproject 설명 문구 고치는 작은 패치를 제안해줘").risk == "medium"
    # trivial alone (a typo fix)
    assert a.analyze("README 오타 하나 고쳐줘").risk == "medium"
    # advisory alone, English
    assert a.analyze("suggest a one-line fix to the wording").risk == "medium"
    # a genuine fix/refactor with no small-scope signal stays high
    assert a.analyze("이 함수 리팩터링 해줘").risk == "high"
    assert a.analyze("이 python repo 버그 고쳐줘").risk == "high"
    # destructive wins regardless of a small-scope word
    assert a.analyze("작은 마이그레이션이지만 prod db 초기화해줘").risk == "high"


# --- routing metadata integration ------------------------------------------

def test_load_systems_routing_reads_four_packs(monkeypatch):
    monkeypatch.setenv("AMMO_ROOT", str(REPO_ROOT))
    routing = _load_systems_routing()
    assert {r["id"] for r in routing} == {"personal", "research", "coding", "ops"}


def test_default_analyzer_uses_real_routing(monkeypatch):
    monkeypatch.setenv("AMMO_ROOT", str(REPO_ROOT))
    vector = TaskAnalyzer().analyze("이 Python repo 버그 고쳐줘")
    assert vector.candidate_systems == ["coding"]


# --- CLI --------------------------------------------------------------------

def test_cli_analyze_outputs_json(monkeypatch, capsys):
    monkeypatch.setenv("AMMO_ROOT", str(REPO_ROOT))
    code = cli.main(["analyze", "이 Python repo 버그 고치고 테스트 추가해줘"])
    out = capsys.readouterr().out
    assert code == 0
    data = json.loads(out)
    assert data["domain"] == "coding"
    assert data["needs_tests"] is True
    assert data["candidate_systems"] == ["coding"]
    # ensure_ascii=False keeps Korean readable in the output
    assert "버그" in out
