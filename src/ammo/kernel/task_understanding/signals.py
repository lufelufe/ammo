"""Keyword lexicons and the matching helper for the rule-based analyzer.

Bilingual (Korean + English). ASCII terms match on word boundaries (so "test"
does not fire on "latest"); non-ASCII (Korean) terms match as substrings, since
Korean has no whitespace tokenization here. All matching is done on the
lower-cased input.
"""

from __future__ import annotations

import re
from typing import Iterable

# --- matching ---------------------------------------------------------------


def contains(text: str, terms: Iterable[str]) -> bool:
    """True if any term is present (word-boundary for ASCII, substring for KR)."""
    for term in terms:
        if term.isascii():
            if re.search(r"\b" + re.escape(term) + r"\b", text):
                return True
        elif term in text:
            return True
    return False


def count(text: str, terms: Iterable[str]) -> int:
    """How many distinct terms match — used for domain scoring."""
    return sum(1 for term in terms if contains(text, [term]))


# --- domain lexicons --------------------------------------------------------

CODING = [
    "코드", "코딩", "버그", "고쳐", "고치", "디버그", "리팩", "리팩터", "구현",
    "함수", "클래스", "커밋", "코드베이스", "깃",
    "code", "coding", "bug", "bugs", "fix", "debug", "refactor", "implement",
    "function", "class", "commit", "merge", "repo", "repository", "pull request",
    "pr", "git", "compile", "build", "lint", "stack trace", "exception",
    "codebase", "pytest",
]

RESEARCH = [
    "연구", "조사", "자료", "논문", "문헌", "출처", "근거", "리서치", "검증",
    "research", "investigate", "literature", "paper", "papers", "sources",
    "evidence", "cite", "citation", "citations", "survey", "fact check",
    "팩트체크",
]

INVESTMENT = [
    "투자", "주식", "주가", "증시", "시세", "시황", "코인", "비트코인", "이더",
    "포트폴리오", "수익률", "배당", "금리", "환율", "부동산", "시장",
    "invest", "investment", "stock", "stocks", "crypto", "bitcoin", "btc",
    "eth", "ticker", "portfolio", "market", "dividend", "real estate",
    "nvda", "tsla",
]

PERSONAL = [
    "할일", "할 일", "일정", "캘린더", "오늘", "브리핑", "리마인더", "메모",
    "나의", "개인", "todo", "calendar", "reminder", "briefing", "agenda",
    "my day",
]

OPS = [
    "운영", "배포", "서버", "크론", "스케줄", "모니터", "점검", "백업", "로그",
    "유지보수", "복원", "재시작",
    "ops", "deploy", "deployment", "server", "cron", "schedule", "monitor",
    "backup", "log", "logs", "maintenance", "pipeline", "restart",
    "health check", "release",
]

WRITING = [
    "작성", "써줘", "써 줘", "글", "에세이", "이메일", "메일", "편지", "블로그",
    "포스트", "초안", "카피", "번역",
    "write", "draft", "essay", "email", "letter", "blog", "post", "compose",
    "rewrite", "proofread", "translate",
]

# --- cross-cutting signal sets ---------------------------------------------

CURRENT_INFO = [
    "오늘", "뉴스", "최신", "현재", "지금", "시세", "주가", "실시간", "요즘",
    "이번 주",
    "today", "news", "latest", "current", "now", "price", "real-time",
    "realtime", "this week",
]

TESTS = [
    "테스트", "커버리지", "단위테스트", "tdd",
    "test", "tests", "coverage", "unit test",
]

CODE_EXECUTION = [
    "실행", "돌려", "빌드",
    "run", "build", "compile", "pytest", "execute",
]

DESTRUCTIVE = [
    "삭제", "지워", "지우", "배포", "마이그레이션", "초기화",
    "drop table", "rm -rf", "reset --hard", "force push", "force-push",
    "migrate", "deploy", "production", "prod",
]

MONEY_MOVE = [
    "매수", "매도", "송금", "이체", "주문 넣",
    "buy", "sell", "transfer", "wire",
]

DECISION = [
    "사야", "팔아", "추천",
    "should i buy", "should i sell", "recommend",
]

SEND_WRITE = [
    "보내", "전송", "저장해",
    "send", "save file", "write file", "upload",
]

# --- intent sub-signals -----------------------------------------------------

REVIEW = ["리뷰", "검토", "review", "code review"]
DEBUG = ["버그", "고쳐", "고치", "디버그", "bug", "bugs", "fix", "debug"]
REFACTOR = ["리팩", "리팩터", "refactor"]
EXPLAIN = ["설명", "구조", "이해", "explain", "understand", "walk me through"]
IMPLEMENT = ["구현", "추가", "만들", "작성", "implement", "add", "create", "build"]

VERIFY = ["검증", "근거", "사실", "fact check", "verify", "팩트체크"]
LITERATURE = [
    "조사", "자료", "논문", "문헌", "literature", "paper", "papers", "survey",
    "sources",
]
SYNTHESIZE = ["정리", "요약", "synthesize", "summary", "summarize"]

SCHEDULE = ["스케줄", "크론", "매일", "정기", "schedule", "cron", "daily", "every"]
MONITOR = ["모니터", "점검", "상태", "monitor", "health"]
DEPLOY = ["배포", "릴리스", "deploy", "release"]

BRIEFING = [
    "브리핑", "오늘", "할일", "할 일", "정리", "요약", "agenda",
    "briefing", "my day",
]

# --- programming languages (for tags) --------------------------------------

LANGUAGES = (
    ("python", ["python", "파이썬", "pytest"]),
    ("javascript", ["javascript", "node", "node.js", "자바스크립트", "js"]),
    ("typescript", ["typescript", "타입스크립트", "ts"]),
    ("rust", ["rust", "러스트"]),
    ("go", ["golang", "go"]),
    ("java", ["java"]),
    ("sql", ["sql"]),
)
