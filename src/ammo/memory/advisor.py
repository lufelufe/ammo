"""MemoryAdvisor — turn recorded performance into a team-formation bias.

Philosophy: memory *advises*, the kernel *decides*. This produces a bounded
bonus (never larger than a capability match) that nudges model selection toward
what has worked, and — via a proven team's per-slot preference — lets a winning
team re-assemble naturally. It never overrides capability/risk/template rules.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

# tuning constants (calibration is a backlog item)
MIN_ATTEMPTS = 2          # ignore stats below this many samples (cold start)
MODEL_WEIGHT = 2.0        # per-model success bias
SYNERGY_WEIGHT = 1.0      # bonus for a model that held this role in a winning team
ECONOMY_WEIGHT = 1.0      # objective=cost/speed: bias toward cheap/light models
BONUS_CAP = 2.0           # hard cap; stays < capability match (+3)


def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def _success_rate(row: Dict[str, Any]) -> float:
    attempts = row.get("attempts") or 0
    return (row.get("successes") or 0) / attempts if attempts else 0.0


def _parse_signature(signature: str) -> Dict[str, str]:
    """'role:model+role:model' -> {role: model}."""
    pairs: Dict[str, str] = {}
    for token in signature.split("+"):
        if ":" in token:
            role, model = token.split(":", 1)
            pairs[role] = model
    return pairs


class MemoryAdvisor:
    def __init__(
        self,
        model_stats: Dict[Tuple[str, str], Dict[str, Any]],
        best_teams: Dict[str, Dict[str, Any]],
        explore: float = 0.0,
    ):
        # model_stats keyed by (model_id, task_tag); best_teams keyed by task_tag
        self._model_stats = model_stats
        self._best_teams = best_teams
        # exploration: a small nudge to under-tried qualified models so a stuck
        # winner can be dethroned. Deterministic (based on attempt counts).
        self._explore = max(0.0, explore)

    @classmethod
    def from_store(cls, store, explore: float = 0.0) -> "MemoryAdvisor":
        model_stats = {
            (r["model_id"], r["task_tag"]): r for r in store.all_model_performance()
        }
        best_teams: Dict[str, Dict[str, Any]] = {}
        for row in store.all_team_synergy():
            tag = row["task_tag"]
            current = best_teams.get(tag)
            if current is None or (_success_rate(row), row["average_confidence"]) > (
                _success_rate(current), current["average_confidence"]
            ):
                best_teams[tag] = row
        return cls(model_stats, best_teams, explore=explore)

    def _economy_term(self, model_id: str, tag: str, metric: str) -> Tuple[float, List[str]]:
        """0..ECONOMY_WEIGHT bonus for being cheap/light relative to peers in this tag."""
        stat = self._model_stats.get((model_id, tag))
        if not stat or (stat.get("attempts") or 0) < MIN_ATTEMPTS:
            return 0.0, []
        value = stat.get(metric) or 0.0
        peers = [
            (s.get(metric) or 0.0)
            for (m, t), s in self._model_stats.items()
            if t == tag and (s.get("attempts") or 0) >= MIN_ATTEMPTS
        ]
        peak = max(peers) if peers else 0.0
        if peak <= 0:
            return 0.0, []
        term = ECONOMY_WEIGHT * (1 - value / peak)
        label = "cheap" if metric == "average_cost" else "light"
        return term, ([f"{label} in {tag} history"] if term >= 0.25 else [])

    def bonus(self, model_id: str, role: str, tag: str,
              objective: str = "balanced") -> Tuple[float, List[str]]:
        """Return (bonus, reasons). Bounded to +/- BONUS_CAP.

        `objective` folds tracked economics into the improvement loop:
        "cost" favors models with low recorded average_cost for this tag,
        "speed" favors low average_tokens (lighter → faster).
        """
        total = 0.0
        reasons: List[str] = []

        stat = self._model_stats.get((model_id, tag))
        attempts = (stat.get("attempts") or 0) if stat else 0
        if stat and attempts >= MIN_ATTEMPTS:
            rate = _success_rate(stat)
            avg = stat.get("average_confidence") or 0.0
            term = _clamp(MODEL_WEIGHT * (rate - 0.5) * 2 + (avg - 0.5), -BONUS_CAP, BONUS_CAP)
            total += term
            if abs(term) >= 0.25:
                quality = "strong" if term > 0 else "weak"
                reasons.append(f"{quality} {tag} history ({rate:.0%} of {stat['attempts']})")
        elif self._explore > 0:
            # under-explored qualified model: give it a chance to be tried
            total += self._explore
            reasons.append("under-explored (exploration)")

        best = self._best_teams.get(tag)
        if best and (best.get("attempts") or 0) >= MIN_ATTEMPTS and _success_rate(best) > 0.5:
            if _parse_signature(best["team_signature"]).get(role) == model_id:
                total += SYNERGY_WEIGHT
                reasons.append(f"proven in winning {tag} team")

        if objective == "cost":
            term, why = self._economy_term(model_id, tag, "average_cost")
            total += term
            reasons += why
        elif objective == "speed":
            term, why = self._economy_term(model_id, tag, "average_tokens")
            total += term
            reasons += why

        return round(_clamp(total, -BONUS_CAP, BONUS_CAP), 3), reasons
