"""Memory Feedback v0 — a SQLite record of what AMMO has run.

This is the seed of AMMO's learning loop: every run is logged, and per-model and
per-team aggregates are updated so later milestones can bias team formation
toward what has worked. v0 only *records* — it does not yet change behavior.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional

from ammo.kernel.team_formation.execution_plan import ExecutionPlan

_SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    run_id           TEXT PRIMARY KEY,
    timestamp        TEXT NOT NULL,
    domain           TEXT,
    tags             TEXT,   -- json array
    selected_system  TEXT,
    selected_models  TEXT,   -- json array of model ids
    team_signature   TEXT,
    confidence_score REAL,
    outcome_status   TEXT,
    user_feedback    TEXT,
    total_tokens     INTEGER,
    estimated_cost   REAL
);

CREATE TABLE IF NOT EXISTS model_performance (
    model_id           TEXT NOT NULL,
    task_tag           TEXT NOT NULL,
    attempts           INTEGER NOT NULL DEFAULT 0,
    successes          INTEGER NOT NULL DEFAULT 0,
    average_confidence REAL NOT NULL DEFAULT 0,
    last_used_at       TEXT,
    average_tokens     REAL NOT NULL DEFAULT 0,
    average_cost       REAL NOT NULL DEFAULT 0,
    PRIMARY KEY (model_id, task_tag)
);

CREATE TABLE IF NOT EXISTS team_synergy (
    team_signature     TEXT NOT NULL,
    task_tag           TEXT NOT NULL,
    attempts           INTEGER NOT NULL DEFAULT 0,
    successes          INTEGER NOT NULL DEFAULT 0,
    average_confidence REAL NOT NULL DEFAULT 0,
    average_cost       REAL NOT NULL DEFAULT 0,
    PRIMARY KEY (team_signature, task_tag)
);
"""


def team_signature(plan: ExecutionPlan) -> str:
    """A stable signature for a team composition (role:model pairs, sorted)."""
    return "+".join(sorted(f"{m.role}:{m.model}" for m in plan.selected_team))


def outcome_from_confidence(score: Optional[float]) -> str:
    if score is None:
        return "unknown"
    if score >= 0.75:
        return "success"
    if score >= 0.5:
        return "acceptable"
    if score >= 0.25:
        return "weak"
    return "failed"


def _is_success(score: Optional[float]) -> bool:
    return score is not None and score >= 0.5


def _signature_models(signature: str) -> List[str]:
    """Model ids referenced by a 'role:model+role:model' team signature."""
    return [token.split(":", 1)[1] for token in signature.split("+") if ":" in token]


class MemoryStore:
    def __init__(self, db_path: Path):
        self.path = Path(db_path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.path))
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(_SCHEMA)
        self._migrate()

    def _migrate(self) -> None:
        """Add columns introduced after a table's first version (old DBs).

        `CREATE TABLE IF NOT EXISTS` never alters an existing table, so a DB made
        before a column existed would be missing it. Columns added after v1 are
        listed here and back-filled with ALTER TABLE ADD COLUMN.
        """
        added_columns = {
            "runs": {
                "team_signature": "TEXT",              # added in M15
                "total_tokens": "INTEGER",             # added in M17 (economics)
                "estimated_cost": "REAL",
            },
            "model_performance": {
                "average_tokens": "REAL NOT NULL DEFAULT 0",   # added in M17
                "average_cost": "REAL NOT NULL DEFAULT 0",
            },
            "team_synergy": {
                "average_cost": "REAL NOT NULL DEFAULT 0",     # added in M17
            },
        }
        for table, columns in added_columns.items():
            existing = {row["name"] for row in self.conn.execute(f"PRAGMA table_info({table})")}
            for name, decl in columns.items():
                if name not in existing:
                    self.conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {decl}")
        self.conn.commit()

    @classmethod
    def open(cls, root: Path) -> "MemoryStore":
        return cls(Path(root) / "memory" / "ammo.sqlite")

    def close(self) -> None:
        self.conn.close()

    def __enter__(self) -> "MemoryStore":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # -- writing ------------------------------------------------------------

    def record_run(
        self,
        *,
        run_id: str,
        timestamp: str,
        domain: str,
        tags: List[str],
        selected_system: Optional[str],
        model_ids: List[str],
        team_signature: str,
        confidence_score: Optional[float],
        outcome_status: Optional[str] = None,
        user_feedback: Optional[str] = None,
        total_tokens: Optional[int] = None,
        estimated_cost: Optional[float] = None,
        model_usage: Optional[Dict[str, Dict[str, float]]] = None,
    ) -> str:
        """Record one run. ``model_usage`` maps model_id -> {tokens, cost} so the
        improvement loop can learn cost-efficiency per model, not just quality."""
        status = outcome_status or outcome_from_confidence(confidence_score)
        success = _is_success(confidence_score)
        # Attribute performance to the SYSTEM (directory), falling back to domain.
        # For built-in packs system == domain, so this generalizes without churn.
        tag = selected_system or domain or "general"
        model_usage = model_usage or {}

        with self.conn:  # one transaction
            self.conn.execute(
                "INSERT OR REPLACE INTO runs "
                "(run_id, timestamp, domain, tags, selected_system, selected_models, "
                " team_signature, confidence_score, outcome_status, user_feedback, "
                " total_tokens, estimated_cost) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (run_id, timestamp, domain, json.dumps(tags), selected_system,
                 json.dumps(model_ids), team_signature, confidence_score, status,
                 user_feedback, total_tokens, estimated_cost),
            )
            for model_id in model_ids:
                usage = model_usage.get(model_id, {})
                self._bump_model(model_id, tag, confidence_score, success, timestamp,
                                 usage.get("tokens", 0.0), usage.get("cost", 0.0))
            self._bump_team(team_signature, tag, confidence_score, success,
                            estimated_cost or 0.0)
        return status

    def _bump_model(self, model_id, tag, score, success, timestamp,
                    tokens: float = 0.0, cost: float = 0.0) -> None:
        row = self.conn.execute(
            "SELECT attempts, successes, average_confidence, average_tokens, average_cost "
            "FROM model_performance WHERE model_id=? AND task_tag=?", (model_id, tag)
        ).fetchone()
        if row:
            attempts, successes, avg = row["attempts"], row["successes"], row["average_confidence"]
            avg_tokens, avg_cost = row["average_tokens"] or 0.0, row["average_cost"] or 0.0
        else:
            attempts, successes, avg, avg_tokens, avg_cost = 0, 0, 0.0, 0.0, 0.0
        new_attempts = attempts + 1
        new_avg = (avg * attempts + (score or 0.0)) / new_attempts
        new_tokens = (avg_tokens * attempts + tokens) / new_attempts
        new_cost = (avg_cost * attempts + cost) / new_attempts
        self.conn.execute(
            "INSERT OR REPLACE INTO model_performance "
            "(model_id, task_tag, attempts, successes, average_confidence, last_used_at, "
            " average_tokens, average_cost) VALUES (?,?,?,?,?,?,?,?)",
            (model_id, tag, new_attempts, successes + (1 if success else 0),
             round(new_avg, 3), timestamp, round(new_tokens, 1), round(new_cost, 6)),
        )

    def _bump_team(self, signature, tag, score, success, cost: float = 0.0) -> None:
        row = self.conn.execute(
            "SELECT attempts, successes, average_confidence, average_cost FROM team_synergy "
            "WHERE team_signature=? AND task_tag=?", (signature, tag)
        ).fetchone()
        if row:
            attempts, successes, avg = row["attempts"], row["successes"], row["average_confidence"]
            avg_cost = row["average_cost"] or 0.0
        else:
            attempts, successes, avg, avg_cost = 0, 0, 0.0, 0.0
        new_attempts = attempts + 1
        new_avg = (avg * attempts + (score or 0.0)) / new_attempts
        new_cost = (avg_cost * attempts + cost) / new_attempts
        self.conn.execute(
            "INSERT OR REPLACE INTO team_synergy "
            "(team_signature, task_tag, attempts, successes, average_confidence, average_cost) "
            "VALUES (?,?,?,?,?,?)",
            (signature, tag, new_attempts, successes + (1 if success else 0),
             round(new_avg, 3), round(new_cost, 6)),
        )

    # -- reading ------------------------------------------------------------

    def list_runs(self, limit: int = 20) -> List[Dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT * FROM runs ORDER BY timestamp DESC, run_id DESC LIMIT ?", (limit,)
        ).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["tags"] = json.loads(d["tags"] or "[]")
            d["selected_models"] = json.loads(d["selected_models"] or "[]")
            out.append(d)
        return out

    def best_team_for_system(self, system_id: str) -> Optional[Dict[str, Any]]:
        """The best-performing team signature recorded for a system (or None).

        Aggregates this system's runs by team signature and ranks by success rate
        then average confidence — 'the best combination for this directory'.
        """
        rows = self.conn.execute(
            "SELECT team_signature, confidence_score FROM runs "
            "WHERE selected_system=? AND team_signature IS NOT NULL", (system_id,)
        ).fetchall()
        agg: Dict[str, Dict[str, float]] = {}
        for row in rows:
            sig = row["team_signature"]
            bucket = agg.setdefault(sig, {"attempts": 0, "successes": 0, "sum": 0.0})
            score = row["confidence_score"] or 0.0
            bucket["attempts"] += 1
            bucket["sum"] += score
            if score >= 0.5:
                bucket["successes"] += 1
        if not agg:
            return None
        best = max(agg, key=lambda s: (agg[s]["successes"] / agg[s]["attempts"],
                                       agg[s]["sum"] / agg[s]["attempts"]))
        b = agg[best]
        return {
            "team_signature": best,
            "attempts": int(b["attempts"]),
            "successes": int(b["successes"]),
            "average_confidence": round(b["sum"] / b["attempts"], 3),
        }

    def runs_for_system(self, system_id: str) -> List[Dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT * FROM runs WHERE selected_system=? ORDER BY timestamp DESC", (system_id,)
        ).fetchall()
        return [dict(r) for r in rows]

    # -- user feedback: ground truth for calibration ---------------------------

    def apply_feedback(self, run_id: str, good: bool, note: str = "") -> Dict[str, Any]:
        """Record the user's verdict on a run and CORRECT the improvement loop.

        Success was credited from confidence (>= 0.5) at record time; when the
        user's verdict contradicts that proxy, the run's models/team get their
        success counts adjusted so future formation learns from truth.
        """
        row = self.conn.execute(
            "SELECT * FROM runs WHERE run_id=?", (run_id,)
        ).fetchone()
        if row is None:
            raise KeyError(f"unknown run: {run_id}")
        run = dict(row)
        proxy_success = _is_success(run.get("confidence_score"))
        verdict = "good" if good else "bad"
        feedback = f"{verdict}: {note}" if note else verdict

        delta = 0
        if good and not proxy_success:
            delta = 1        # under-credited: the proxy called it a failure
        elif not good and proxy_success:
            delta = -1       # over-credited: the proxy called it a success

        tag = run.get("selected_system") or run.get("domain") or "general"
        with self.conn:
            self.conn.execute(
                "UPDATE runs SET user_feedback=? WHERE run_id=?", (feedback, run_id)
            )
            if delta:
                for model_id in json.loads(run.get("selected_models") or "[]"):
                    self.conn.execute(
                        "UPDATE model_performance SET successes=MAX(0, successes+?) "
                        "WHERE model_id=? AND task_tag=?", (delta, model_id, tag)
                    )
                self.conn.execute(
                    "UPDATE team_synergy SET successes=MAX(0, successes+?) "
                    "WHERE team_signature=? AND task_tag=?",
                    (delta, run.get("team_signature"), tag)
                )
        return {"run_id": run_id, "feedback": feedback, "corrected": delta}

    def feedback_rows(self) -> List[Dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT run_id, confidence_score, user_feedback FROM runs "
            "WHERE user_feedback IS NOT NULL ORDER BY timestamp"
        ).fetchall()
        return [dict(r) for r in rows]

    # -- dream / consolidation primitives ------------------------------------

    def model_cost_snapshot(self) -> Dict[str, Dict[str, float]]:
        """Per-model avg tokens/cost (attempt-weighted across tags).

        Per-run per-model usage is not stored in `runs`, so a rebuild cannot
        recompute these — the snapshot carries the best-known values over.
        """
        snapshot: Dict[str, Dict[str, float]] = {}
        for row in self.all_model_performance():
            m = snapshot.setdefault(row["model_id"], {"attempts": 0, "tokens": 0.0, "cost": 0.0})
            attempts = row["attempts"] or 0
            m["tokens"] += (row["average_tokens"] or 0.0) * attempts
            m["cost"] += (row["average_cost"] or 0.0) * attempts
            m["attempts"] += attempts
        return {
            model: {
                "tokens": (v["tokens"] / v["attempts"]) if v["attempts"] else 0.0,
                "cost": (v["cost"] / v["attempts"]) if v["attempts"] else 0.0,
            }
            for model, v in snapshot.items()
        }

    def rebuild_aggregates(self, runs: List[Dict[str, Any]], known_models) -> None:
        """Rebuild model_performance/team_synergy from the given runs.

        `runs` are consumed oldest-first; models not in `known_models` are
        excluded (orphans); tags are re-derived (system, falling back to
        domain), which also merges legacy domain-keyed rows. Cost/token
        averages are carried over from the pre-rebuild snapshot.
        """
        known = set(known_models)
        snapshot = self.model_cost_snapshot()
        with self.conn:
            self.conn.execute("DELETE FROM model_performance")
            self.conn.execute("DELETE FROM team_synergy")
            for run in runs:
                score = run.get("confidence_score")
                success = _is_success(score)
                tag = run.get("selected_system") or run.get("domain") or "general"
                for model_id in run.get("selected_models") or []:
                    if model_id not in known:
                        continue
                    carried = snapshot.get(model_id, {})
                    self._bump_model(model_id, tag, score, success, run.get("timestamp"),
                                     carried.get("tokens", 0.0), carried.get("cost", 0.0))
                signature = run.get("team_signature")
                if signature and all(
                    m in known for m in _signature_models(signature)
                ):
                    self._bump_team(signature, tag, score, success,
                                    run.get("estimated_cost") or 0.0)

    def prune_runs_keep(self, keep: int) -> List[str]:
        """Delete run rows beyond the newest `keep`; return the deleted ids."""
        rows = self.conn.execute(
            "SELECT run_id FROM runs ORDER BY timestamp DESC, run_id DESC"
        ).fetchall()
        doomed = [r["run_id"] for r in rows[keep:]]
        if doomed:
            with self.conn:
                self.conn.executemany(
                    "DELETE FROM runs WHERE run_id=?", [(rid,) for rid in doomed]
                )
        return doomed

    def all_model_performance(self) -> List[Dict[str, Any]]:
        return [dict(r) for r in self.conn.execute("SELECT * FROM model_performance")]

    def all_team_synergy(self) -> List[Dict[str, Any]]:
        return [dict(r) for r in self.conn.execute("SELECT * FROM team_synergy")]

    def stats(self) -> Dict[str, Any]:
        total = self.conn.execute("SELECT COUNT(*) AS n FROM runs").fetchone()["n"]
        by_domain = {
            row["domain"]: row["n"]
            for row in self.conn.execute(
                "SELECT domain, COUNT(*) AS n FROM runs GROUP BY domain ORDER BY n DESC"
            )
        }
        models = [dict(r) for r in self.conn.execute(
            "SELECT * FROM model_performance ORDER BY attempts DESC, model_id ASC"
        )]
        teams = [dict(r) for r in self.conn.execute(
            "SELECT * FROM team_synergy ORDER BY attempts DESC, team_signature ASC"
        )]
        return {"total_runs": total, "by_domain": by_domain, "models": models, "teams": teams}
