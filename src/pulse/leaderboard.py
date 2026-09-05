"""Trace leaderboard: best/worst traces per task type (anonymized)."""

from __future__ import annotations

from .trace_score import anonymize


def _entry(rec: dict) -> dict:
    return {
        "id_hash": anonymize(str(rec.get("session_id", ""))),
        "model": rec.get("model", ""),
        "score": rec.get("score", 0),
        "signals": [s.get("name", "") if isinstance(s, dict) else str(s) for s in rec.get("signals", [])],
    }


def rank_traces(records: list[dict], top: int = 3) -> dict[str, dict[str, list[dict]]]:
    """Group records by task_type; top/bottom N each (ties: lower cost first)."""
    if not records:
        return {}
    groups: dict[str, list[dict]] = {}
    for rec in records:
        groups.setdefault(str(rec.get("task_type", "coding")), []).append(rec)
    out: dict[str, dict[str, list[dict]]] = {}
    for task, recs in groups.items():
        by_best = sorted(recs, key=lambda r: (-r.get("score", 0), r.get("cost_usd", 0.0)))
        by_worst = sorted(recs, key=lambda r: (r.get("score", 0), r.get("cost_usd", 0.0)))
        out[task] = {"best": [_entry(r) for r in by_best[:top]], "worst": [_entry(r) for r in by_worst[:top]]}
    return out


__all__ = ["rank_traces"]
