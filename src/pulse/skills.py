"""Skill ROI ledger (plan item 2b / A3): per-skill rollup over score records.

Pure aggregation — no new detectors. Inputs: ``active_skills``,
``skill_deadweight`` signal, ``correction_chain`` signal, ``cost_usd``.

Honesty constraint: correlation, not causation. A skill loaded in hard
sessions looks bad through no fault of its own — every card shows the
task-type mix alongside the numbers, plus the mean cost of skill-less
sessions of the same task types as a baseline.
"""

from __future__ import annotations


def _has_signal(rec: dict, name: str) -> bool:
    return any(
        isinstance(s, dict) and s.get("name") == name for s in rec.get("signals", [])
    )


def ledger(records: list[dict]) -> dict[str, dict]:
    """Return {skill: card} where card has loads, rates, costs, task mix."""
    per_skill: dict[str, list[dict]] = {}
    for rec in records:
        for skill in rec.get("active_skills", []) or []:
            per_skill.setdefault(str(skill), []).append(rec)
    # Baseline: mean cost of skill-less sessions, per task type.
    baseline_costs: dict[str, list[float]] = {}
    for rec in records:
        if not rec.get("active_skills"):
            task = str(rec.get("task_type", "coding"))
            baseline_costs.setdefault(task, []).append(float(rec.get("cost_usd", 0.0)))
    baseline_mean = {
        task: round(sum(v) / len(v), 4) for task, v in baseline_costs.items()
    }
    out: dict[str, dict] = {}
    for skill in sorted(per_skill):
        recs = per_skill[skill]
        n = len(recs)
        dw = sum(1 for r in recs if _has_signal(r, "skill_deadweight"))
        corr = sum(1 for r in recs if _has_signal(r, "correction_chain"))
        costs = [float(r.get("cost_usd", 0.0)) for r in recs]
        task_mix: dict[str, int] = {}
        for r in recs:
            task = str(r.get("task_type", "coding"))
            task_mix[task] = task_mix.get(task, 0) + 1
        mix_costs = [
            baseline_mean[t] for t in task_mix if t in baseline_mean
        ]
        out[skill] = {
            "loads": n,
            "deadweight_rate": round(dw / n, 2) if n else 0.0,
            "correction_rate": round(corr / n, 2) if n else 0.0,
            "mean_cost": round(sum(costs) / n, 4) if n else 0.0,
            "task_mix": task_mix,
            "baseline_cost_same_task": (
                round(sum(mix_costs) / len(mix_costs), 4) if mix_costs else 0.0
            ),
        }
    return out


__all__ = ["ledger"]
