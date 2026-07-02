"""Eval cases — sample tasks with expected outcomes.

Loaded from ``evals/*.yaml``. Each case pairs an input with expectations the eval
suite scores against, so AMMO's decisions can be measured over time.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List


@dataclass
class EvalCase:
    id: str
    input: str
    expect: Dict[str, Any] = field(default_factory=dict)


def load_cases(evals_dir: Path) -> List[EvalCase]:
    import yaml

    cases: List[EvalCase] = []
    evals_dir = Path(evals_dir)
    if not evals_dir.is_dir():
        return cases
    for path in sorted(evals_dir.glob("*.yaml")):
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        for entry in data.get("cases", []) or []:
            cases.append(EvalCase(id=entry["id"], input=entry["input"],
                                  expect=entry.get("expect", {})))
    return cases
