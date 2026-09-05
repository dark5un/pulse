"""Judge-vs-deterministic agreement (B2): numbers before hosted-judge claims.

Comparable pairs: correction_quality(finding=no, i.e. judge says the
correction was vague) <-> deterministic correction_chain present; judge
goal_completion(finding=no, problem found) <-> deterministic premature_stop
present. Non-overlapping signals (hallucination, context_retention) report
judge positive-rate + require human spot-check, never kappa.

Gate: no "Pulse scores, but ML" claims until kappa >= 0.6 at n >= 50 on a
pinned corpus. `pulse agreement` prints PASS/FAIL against that gate.
"""

from __future__ import annotations

KAPPA_GATE = 0.6
N_GATE = 50


def cohen_kappa(a: list[int], b: list[int]) -> float:
    """Cohen's kappa for two binary label lists. 0.0 when undefined."""
    n = len(a)
    if n == 0 or len(b) != n:
        return 0.0
    tp = sum(1 for x, y in zip(a, b) if x == 1 and y == 1)
    tn = sum(1 for x, y in zip(a, b) if x == 0 and y == 0)
    fp = sum(1 for x, y in zip(a, b) if x == 0 and y == 1)
    fn = sum(1 for x, y in zip(a, b) if x == 1 and y == 0)
    po = (tp + tn) / n
    pe = ((tp + fp) * (tp + fn) + (tn + fp) * (tn + fn)) / (n * n)
    if pe == 1.0:
        return 0.0
    return round((po - pe) / (1 - pe), 3)


def agreement_rate(a: list[int], b: list[int]) -> dict:
    """Raw match rate + confusion counts (no chance correction)."""
    n = len(a)
    tp = sum(1 for x, y in zip(a, b) if x == 1 and y == 1)
    tn = sum(1 for x, y in zip(a, b) if x == 0 and y == 0)
    fp = sum(1 for x, y in zip(a, b) if x == 0 and y == 1)
    fn = sum(1 for x, y in zip(a, b) if x == 1 and y == 0)
    return {
        "n": n,
        "rate": round((tp + tn) / n, 3) if n else 0.0,
        "confusion": {"tp": tp, "tn": tn, "fp": fp, "fn": fn},
    }


def gate(kappa: float, n: int) -> dict:
    """PASS only when kappa >= 0.6 AND n >= 50."""
    passed = kappa >= KAPPA_GATE and n >= N_GATE
    return {"pass": passed, "kappa_gate": KAPPA_GATE, "n_gate": N_GATE}


__all__ = ["KAPPA_GATE", "N_GATE", "agreement_rate", "cohen_kappa", "gate"]
