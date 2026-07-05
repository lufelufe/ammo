"""Confidence calibration — turn user verdicts into a bounded correction.

The engine's weights are hand-tuned constants; the user's good/bad verdicts
(`ammo feedback`) are the ground truth they were never tuned against. This
module compares each band's empirical good-rate with the score range the band
claims and derives ONE transparent, bounded global offset — enough to shift
systematically optimistic/pessimistic scores toward reality. Per-term weight
re-tuning needs far more data and stays out of scope (docs/BACKLOG.md).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

# a suggestion needs a minimal sample; a correction stays small and reversible
MIN_SAMPLES = 10
OFFSET_CAP = 0.15

BANDS = [
    ("very_low", 0.0, 0.25),
    ("low", 0.25, 0.5),
    ("medium", 0.5, 0.75),
    ("high", 0.75, 1.0),
]


@dataclass
class BandStat:
    band: str
    lo: float
    hi: float
    n: int
    good_rate: float

    @property
    def verdict(self) -> str:
        if self.good_rate < self.lo:
            return "overconfident"
        if self.good_rate >= self.hi:
            return "underconfident"
        return "calibrated"


@dataclass
class Calibration:
    samples: int
    bands: List[BandStat] = field(default_factory=list)
    # None until MIN_SAMPLES verdicts exist; then a clamped global offset
    suggested_offset: Optional[float] = None


def _is_good(row: Dict[str, Any]) -> bool:
    return str(row.get("user_feedback") or "").startswith("good")


def calibrate(rows: List[Dict[str, Any]]) -> Calibration:
    """Band stats + a suggested global offset from judged runs.

    The offset is the sample-weighted mean gap between each band's empirical
    good-rate and the band's midpoint (what the score range claims), clamped
    to +/-OFFSET_CAP: scores judged worse than they claim pull the offset
    negative, better pull it positive.
    """
    scored = [r for r in rows if r.get("confidence_score") is not None]
    result = Calibration(samples=len(scored))
    weighted_gap = 0.0
    for band, lo, hi in BANDS:
        in_band = [r for r in scored
                   if lo <= r["confidence_score"] and
                   (r["confidence_score"] < hi or hi == 1.0)]
        if not in_band:
            continue
        good_rate = sum(1 for r in in_band if _is_good(r)) / len(in_band)
        result.bands.append(BandStat(band, lo, hi, len(in_band), good_rate))
        weighted_gap += len(in_band) * (good_rate - (lo + hi) / 2)
    if result.samples >= MIN_SAMPLES:
        offset = weighted_gap / result.samples
        result.suggested_offset = round(
            max(-OFFSET_CAP, min(OFFSET_CAP, offset)), 2)
    return result
