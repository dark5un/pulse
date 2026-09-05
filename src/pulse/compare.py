"""Distribution comparison over score records (plan item 2 / A2).

Pure functions: mean/median/p25/p75 per variant, cost delta, timing delta,
and a plain-English verdict. No significance testing at v1 — effect size
+ N, labeled provisional like every other threshold in this repo.
"""

from __future__ import annotations


def _quantile(sorted_vals: list[float], q: float) -> float:
    if not sorted_vals:
        return 0.0
    if len(sorted_vals) == 1:
        return sorted_vals[0]
    pos = q * (len(sorted_vals) - 1)
    lo = int(pos)
    hi = min(lo + 1, len(sorted_vals) - 1)
    frac = pos - lo
    return round(sorted_vals[lo] * (1 - frac) + sorted_vals[hi] * frac, 2)


def summarize(values: list[float]) -> dict:
    """{n, mean, median, p25, p75} over a value list."""
    vals = sorted(float(v) for v in values)
    n = len(vals)
    if not n:
        return {"n": 0, "mean": 0.0, "median": 0.0, "p25": 0.0, "p75": 0.0}
    return {
        "n": n,
        "mean": round(sum(vals) / n, 2),
        "median": _quantile(vals, 0.5),
        "p25": _quantile(vals, 0.25),
        "p75": _quantile(vals, 0.75),
    }


def _scores(records: list[dict]) -> list[float]:
    return [float(r.get("score", 0)) for r in records]


def _costs(records: list[dict]) -> list[float]:
    return [float(r.get("cost_usd", 0.0)) for r in records]


def _timing(records: list[dict]) -> list[float]:
    vals = []
    for r in records:
        for key in ("duration_ms", "original_duration_ms", "replay_duration_ms"):
            if key in r and r[key] is not None:
                try:
                    vals.append(float(r[key]))  # type: ignore[index]
                    break
                except (TypeError, ValueError):
                    continue
    return vals


def compare_distributions(a: list[dict], b: list[dict]) -> dict:
    """Compare two record lists. Returns summaries, deltas (A minus B), verdict."""
    sa = summarize(_scores(a))
    sb = summarize(_scores(b))
    ca = summarize(_costs(a))
    cb = summarize(_costs(b))
    ta = summarize(_timing(a))
    tb = summarize(_timing(b))
    score_delta = round(sa["mean"] - sb["mean"], 2)
    cost_delta = round(ca["mean"] - cb["mean"], 4)
    timing_delta = round(ta["mean"] - tb["mean"], 2)
    n = min(sa["n"], sb["n"])
    if sa["n"] == 0 or sb["n"] == 0:
        verdict = "no data on one side — collect traces for both variants first"
    elif abs(score_delta) <= 1.0:
        verdict = (
            f"A ties B on quality ({score_delta:+.1f} pts, "
            f"cost {cost_delta:+.4f}, provisional n={n})"
        )
    elif score_delta > 0:
        verdict = (
            f"A wins on quality ({score_delta:+.1f} pts, "
            f"cost {cost_delta:+.4f}, provisional n={n})"
        )
    else:
        verdict = (
            f"B wins on quality ({score_delta:+.1f} pts, "
            f"cost {cost_delta:+.4f}, provisional n={n})"
        )
    return {
        "a": sa,
        "b": sb,
        "cost_a": ca,
        "cost_b": cb,
        "timing_a": ta,
        "timing_b": tb,
        "score_delta": score_delta,
        "cost_delta": cost_delta,
        "timing_delta": timing_delta,
        "verdict": verdict,
    }


__all__ = ["compare_distributions", "summarize"]
