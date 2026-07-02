"""Run logging — persist every run under ``runtime/runs/<run_id>/``.

This is where AMMO's memory begins. Each run writes a fixed set of artifacts so
later milestones (Confidence, Memory Feedback) can read what happened. No
secrets are written — only task/plan/output data the kernel produced.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from ammo.kernel.executor.result import ExecutionResult
from ammo.kernel.task_understanding.task_vector import TaskVector
from ammo.kernel.team_formation.execution_plan import ExecutionPlan

# the artifacts written for every run
RUN_FILES = (
    "input.json",
    "task_vector.json",
    "execution_plan.json",
    "step_outputs.json",
    "evidence.json",
    "final_output.md",
    "run_summary.json",
)


def _write_json(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _collect_evidence(result: ExecutionResult) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for response in result.responses:
        for ev in response.evidence:
            rows.append({"role": response.role, "model": response.model, **ev.to_dict()})
    return rows


def _final_markdown(run_id: str, input_text: str, result: ExecutionResult) -> str:
    lines = [
        f"# AMMO Run `{run_id}`",
        "",
        f"**Request:** {input_text}",
        f"**System:** {result.plan.selected_system}",
        f"**Team:** {', '.join(f'{m.role}:{m.model}' for m in result.plan.selected_team)}",
        f"**Aggregate confidence:** {result.aggregate_confidence}",
        "",
        "## Final output",
        "",
        result.final_output or "(none)",
        "",
        "## Steps",
        "",
    ]
    for step in result.responses:
        lines.append(f"- **{step.role}** ({step.model}): {step.output}")
    return "\n".join(lines) + "\n"


class RunStore:
    def __init__(self, root: Path):
        self.root = Path(root)
        self.runs_dir = self.root / "runtime" / "runs"

    def new_run_id(self, now: Optional[datetime] = None) -> str:
        now = now or datetime.now(timezone.utc)
        return now.strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:6]

    def run_path(self, run_id: str) -> Path:
        return self.runs_dir / run_id

    def list_runs(self) -> List[str]:
        if not self.runs_dir.is_dir():
            return []
        return sorted(p.name for p in self.runs_dir.iterdir() if p.is_dir())

    def save(
        self,
        *,
        input_text: str,
        task: TaskVector,
        plan: ExecutionPlan,
        result: ExecutionResult,
        confidence: Optional[Dict[str, Any]] = None,
        economics: Optional[Dict[str, Any]] = None,
        sandbox: Optional[str] = None,
        run_id: Optional[str] = None,
        now: Optional[datetime] = None,
    ) -> Tuple[str, Path]:
        now = now or datetime.now(timezone.utc)
        run_id = run_id or self.new_run_id(now)
        created_at = now.isoformat()
        path = self.run_path(run_id)
        path.mkdir(parents=True, exist_ok=True)

        _write_json(path / "input.json", {"run_id": run_id, "created_at": created_at, "input": input_text})
        _write_json(path / "task_vector.json", task.to_dict())
        _write_json(path / "execution_plan.json", plan.to_dict())
        _write_json(path / "step_outputs.json", [r.to_dict() for r in result.responses])
        _write_json(path / "evidence.json", _collect_evidence(result))
        (path / "final_output.md").write_text(
            _final_markdown(run_id, input_text, result), encoding="utf-8"
        )
        if confidence is not None:
            _write_json(path / "confidence_report.json", confidence)
        _write_json(
            path / "run_summary.json",
            {
                "run_id": run_id,
                "created_at": created_at,
                "input": input_text,
                "mode": result.mode,
                "selected_system": plan.selected_system,
                "roles": plan.roles,
                "team": [m.to_dict() for m in plan.selected_team],
                "risk_controls": plan.risk_controls,
                "expected_outputs": plan.expected_outputs,
                "aggregate_confidence": result.aggregate_confidence,
                "confidence": confidence,
                "economics": economics,
                "sandbox": sandbox,
                "final_output": result.final_output,
            },
        )
        return run_id, path

    def load_summary(self, run_id: str) -> Dict[str, Any]:
        path = self.run_path(run_id) / "run_summary.json"
        if not path.is_file():
            raise FileNotFoundError(run_id)
        return json.loads(path.read_text(encoding="utf-8"))
