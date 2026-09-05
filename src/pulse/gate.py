"""Pulse CI gate: compare candidate corpus mean score vs baseline per task type."""

from __future__ import annotations


def _mean(scores: list[float]) -> float:
    return sum(scores) / len(scores) if scores else 0.0


def _by_task(records: list[dict]) -> dict[str, list[float]]:
    groups: dict[str, list[float]] = {}
    for rec in records:
        groups.setdefault(str(rec.get("task_type", "coding")), []).append(float(rec.get("score", 0)))
    return groups


def compare(
    baseline_records: list[dict],
    candidate_records: list[dict],
    tolerance: float = 5.0,
) -> dict:
    """Fail if any task-type mean drops more than tolerance (points).

    Returns {pass, baseline_mean, candidate_mean, delta, detail} where
    detail maps task_type -> {baseline, candidate, drop}.
    """
    base_groups = _by_task(baseline_records)
    cand_groups = _by_task(candidate_records)
    baseline_mean = _mean([float(r.get("score", 0)) for r in baseline_records])
    candidate_mean = _mean([float(r.get("score", 0)) for r in candidate_records])
    detail: dict[str, dict[str, float]] = {}
    passed = True
    for task in sorted(set(base_groups) | set(cand_groups)):
        b, c = _mean(base_groups.get(task, [])), _mean(cand_groups.get(task, []))
        drop = round(b - c, 2)
        detail[task] = {"baseline": round(b, 2), "candidate": round(c, 2), "drop": drop}
        if task in base_groups and drop > tolerance:
            passed = False
    return {
        "pass": passed,
        "baseline_mean": round(baseline_mean, 2),
        "candidate_mean": round(candidate_mean, 2),
        "delta": round(candidate_mean - baseline_mean, 2),
        "detail": detail,
    }


__all__ = ["compare"]
