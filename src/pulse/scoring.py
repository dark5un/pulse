"""Shared score and penalty-attribution semantics."""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass


@dataclass(frozen=True)
class ScoreBreakdown:
    score: int
    status: str
    attribution: dict[str, float]


def score_penalties(penalties: Mapping[str, float]) -> ScoreBreakdown:
    """Return clamped score, display status, and normalized penalty shares."""
    values = {key: max(0.0, float(penalties.get(key, 0.0))) for key in ("user", "agent", "other")}
    total = sum(values.values())
    score = max(0, min(100, round(100 - total)))
    status = "green" if total <= 15 else "yellow" if total <= 30 else "red"
    if total == 0:
        attribution = {key: 0.0 for key in values}
    else:
        attribution = {key: round(value / total * 100, 2) for key, value in values.items()}
        # Keep rounded shares exactly normalized without distorting categories.
        attribution["other"] = round(100.0 - attribution["user"] - attribution["agent"], 2)
    return ScoreBreakdown(score, status, attribution)


__all__ = ["ScoreBreakdown", "score_penalties"]

