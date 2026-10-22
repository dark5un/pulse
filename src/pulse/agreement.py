"""Judge-vs-deterministic agreement (B2 + M4 reporting): numbers before
hosted-judge claims.

Comparable pairs (polarity pinned by ADR 0012 + per-pair truth-table
tests): the verdict prompt defines finding="yes" as "the PROBLEM was
found". A deterministic correction_chain row is an instance of the
correction-quality problem (repeated corrections), so the pair is judge
correction_quality(finding=yes) <-> correction_chain present; likewise
judge goal_completion(finding=yes — goal-completion problem found) <->
deterministic premature_stop present. finding=no is judge-negative
(label 0); unscoreable or an ABSENT verdict abstains (label None) and is
excluded from that pair's kappa only, never counted as "no".
Non-overlapping signals (hallucination, context_retention) report
judge positive-rate + require human spot-check, never kappa.

Per-cell reporting (M4 / ADR 0009): kappa is computed per comparable
pair PER STRATUM (core/enriched — 4 cells); the gate number is the MIN
over the cells at kappa >= 0.6 and post-exclusion n >= 50 per cell.
Every cell carries a distribution block (n, per-rater marginals,
confusion cells, abstain rate, post-exclusion n, truncation counts) and
refuses kappa on degenerate marginals — the pe=1 -> 0.0 sentinel in
``cohen_kappa`` must NEVER reach the gate as a bare FAIL (ML-B6); the
marginal guard fires first. Abstain share over the provisional
MAX_EXCLUSION_SHARE guard -> "not evaluated" (MNAR: kappa would land on
the surviving easy subset, ML-A3). Bootstrap 95% CIs (stdlib random,
ML-B1) ride beside every printed kappa; BORDERLINE when the CI straddles
the bar. Pooled cross-stratum kappa is descriptive-only: it depends on
the mix ratio and estimates nothing natural.

Gate: no "Pulse scores, but ML" claims until kappa >= 0.6 at n >= 50 PER
STRATUM on a pinned corpus. `pulse agreement` prints PASS / FAIL /
NOT-EVALUATED against that gate — a refusal is never a bare FAIL.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field

KAPPA_GATE = 0.6
N_GATE = 50

#: Deep-judge gate M4 (ADR 0009): cells = comparable pairs x strata, and
#: stratum labels come from the selection manifest.
STRATA = ("core", "enriched")

#: ML-A3 PROVISIONAL guard (flagged for user confirmation before the full
#: run): abstain share above this fraction on a cell -> "not evaluated —
#: exclusion share too high". Enriched sessions are long, long sessions
#: truncate, truncation triggers abstain; the surviving subset is MNAR-
#: biased, so a kappa printed over it would overstate comparability.
MAX_EXCLUSION_SHARE = 0.30

#: ML-B1: bootstrap 95% CI per cell (stdlib random, item resampling).
#: Fixed seed string per cell => reruns reproduce CI bounds exactly.
BOOTSTRAP_RESAMPLES = 1000
BOOTSTRAP_SEED = "20261022"


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


def _kappa_or_none(a: list[int], b: list[int]) -> float | None:
    """Kappa, or None when undefined (empty or pe=1) — never the 0.0
    sentinel. Degenerate cells must be REFUSED, not silently reported as
    kappa=0.0 (the September base-rate collapse; ML-B6)."""
    n = len(a)
    if n == 0 or len(b) != n:
        return None
    tp = sum(1 for x, y in zip(a, b) if x == 1 and y == 1)
    tn = sum(1 for x, y in zip(a, b) if x == 0 and y == 0)
    fp = sum(1 for x, y in zip(a, b) if x == 0 and y == 1)
    fn = sum(1 for x, y in zip(a, b) if x == 1 and y == 0)
    pe = ((tp + fp) * (tp + fn) + (tn + fp) * (tn + fn)) / (n * n)
    if pe == 1.0:
        return None
    po = (tp + tn) / n
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
    """PASS only when kappa >= 0.6 AND n >= 50. (Legacy single-number
    form kept for API stability; the v2 gate is ``gate_verdict`` over
    per-pair-per-stratum cells.)"""
    passed = kappa >= KAPPA_GATE and n >= N_GATE
    return {"pass": passed, "kappa_gate": KAPPA_GATE, "n_gate": N_GATE}


def bootstrap_kappa_ci(
    a: list[int],
    b: list[int],
    resamples: int = BOOTSTRAP_RESAMPLES,
    seed: str = BOOTSTRAP_SEED,
) -> tuple[float, float] | None:
    """Percentile 95% CI for Cohen's kappa by resampling item pairs with
    replacement (stdlib random, ML-B1). Undefined resamples (pe=1 draws
    on degenerate inputs) are dropped; None when nothing survives."""
    n = len(a)
    if n == 0:
        return None
    rng = random.Random(f"{seed}:{len(a)}")
    vals: list[float] = []
    for _ in range(resamples):
        idx = [rng.randrange(n) for _ in range(n)]
        k = _kappa_or_none([a[i] for i in idx], [b[i] for i in idx])
        if k is not None:
            vals.append(k)
    if not vals:
        return None
    vals.sort()
    lo = vals[int(0.025 * (len(vals) - 1))]
    hi = vals[int(0.975 * (len(vals) - 1))]
    return (lo, hi)


@dataclass
class CellStats:
    """One pair-x-stratum kappa cell: the distribution block plus the
    kappa verdict or the refusal reason. The block fields ARE the
    product (golden-output tests lock the rendered text)."""

    pair: str
    stratum: str
    n_items: int = 0
    abstained: int = 0
    comparable_n: int = 0
    judge_pos: int = 0
    judge_neg: int = 0
    det_pos: int = 0
    det_neg: int = 0
    confusion: dict[str, int] = field(
        default_factory=lambda: {"tp": 0, "fp": 0, "fn": 0, "tn": 0}
    )
    approx_truncated: int = 0
    fresh_calls: int = 0
    truncated_fresh: int = 0
    kappa: float | None = None
    ci: tuple[float, float] | None = None
    borderline: bool = False
    counts_in_gate: bool = False
    refusal: str = ""

    def to_dict(self) -> dict:
        return {
            "pair": self.pair,
            "stratum": self.stratum,
            "n_items": self.n_items,
            "abstained": self.abstained,
            "abstain_share": round(self.abstained / self.n_items, 3) if self.n_items else 0.0,
            "comparable_n": self.comparable_n,
            "marginals": {
                "judge": {"pos": self.judge_pos, "neg": self.judge_neg},
                "detector": {"pos": self.det_pos, "neg": self.det_neg},
            },
            "confusion": self.confusion,
            "truncation": {
                "measured_fresh": f"{self.truncated_fresh}/{self.fresh_calls}",
                "approx_stamped": f"{self.approx_truncated}/{self.n_items}",
            },
            "kappa": self.kappa,
            "ci95": list(self.ci) if self.ci else None,
            "borderline": self.borderline,
            "counts_in_gate": self.counts_in_gate,
            "refusal": self.refusal or None,
        }


def cell_stats(pair: str, stratum: str, rows: list[tuple]) -> CellStats:
    """Build one kappa cell from rows of
    ``(judge_label_or_None, det_label, approx_truncated, truncated_measured_or_None)``.

    judge None = abstain (excluded from THIS cell only; det labels are
    always recomputed at run time — ML-B7). Refusal order: no items ->
    nothing left after exclusion -> exclusion-share guard -> degenerate
    marginals -> below per-stratum n floor. Only a cell that clears all
    five counts toward the gate.
    """
    c = CellStats(pair=pair, stratum=stratum)
    c.n_items = len(rows)
    comp: list[tuple[int, int]] = []
    for judge, det, approx, trunc in rows:
        if approx:
            c.approx_truncated += 1
        if trunc is not None:
            c.fresh_calls += 1
            if trunc:
                c.truncated_fresh += 1
        if judge is None:
            c.abstained += 1
        else:
            comp.append((int(judge), int(det)))
    c.comparable_n = len(comp)
    c.judge_pos = sum(1 for j, _ in comp if j == 1)
    c.judge_neg = sum(1 for j, _ in comp if j == 0)
    c.det_pos = sum(1 for _, d in comp if d == 1)
    c.det_neg = sum(1 for _, d in comp if d == 0)
    c.confusion = {
        "tp": sum(1 for j, d in comp if j == 1 and d == 1),
        "fp": sum(1 for j, d in comp if j == 0 and d == 1),
        "fn": sum(1 for j, d in comp if j == 1 and d == 0),
        "tn": sum(1 for j, d in comp if j == 0 and d == 0),
    }

    if c.n_items == 0:
        c.refusal = f"no items in stratum {stratum!r} for this pair (the manifest carries none)"
        return c
    if c.comparable_n == 0:
        c.refusal = (
            f"abstention excluded every item (comparable n=0 of {c.n_items}) — "
            "kappa would have no data at all"
        )
        return c
    if c.abstained / c.n_items > MAX_EXCLUSION_SHARE:
        c.refusal = (
            f"exclusion share too high ({100.0 * c.abstained / c.n_items:.1f}% > "
            f"{100.0 * MAX_EXCLUSION_SHARE:.1f}% guard) — kappa would land only on the "
            "surviving easy subset (MNAR, ML-A3)"
        )
        return c
    single: list[str] = []
    if c.judge_pos == 0:
        single.append("judge produced 0 positives")
    elif c.judge_neg == 0:
        single.append("judge produced 0 negatives")
    if c.det_pos == 0:
        single.append("detector produced 0 positives")
    elif c.det_neg == 0:
        single.append("detector produced 0 negatives")
    if single:
        note = ""
        if c.judge_pos == 0 and c.det_pos == 0:
            note = (
                " — the pe=1 base-rate collapse behind September's "
                "'kappa=0.0 / agree=1.0': it would measure the corpus, not the judge"
            )
        c.refusal = f"degenerate labels ({'; '.join(single)}){note}"
        return c
    ja = [j for j, _ in comp]
    da = [d for _, d in comp]
    c.kappa = _kappa_or_none(ja, da)
    if c.kappa is None:  # unreachable given the marginal guards; belt-and-braces
        c.refusal = "degenerate labels (pe=1 sentinel) — kappa refused, never reported as 0.0"
        return c
    c.ci = bootstrap_kappa_ci(ja, da)
    if c.ci is not None:
        c.borderline = c.ci[0] < KAPPA_GATE <= c.ci[1]
    if c.comparable_n < N_GATE:
        c.refusal = (
            f"post-exclusion n={c.comparable_n} below per-stratum floor {N_GATE} — "
            "kappa shown descriptively only, the gate is not evaluated on this cell"
        )
        return c
    c.counts_in_gate = True
    return c


def render_cell(c: CellStats) -> list[str]:
    """The product text: distribution block BEFORE any kappa, then the
    kappa line or the explicit refusal. Golden-output tests lock this."""
    lines = [
        f"── kappa cell: {c.pair} × {c.stratum} " + "─" * 12,
        (
            f"  items={c.n_items} abstained={c.abstained}"
            + (f" ({100.0 * c.abstained / c.n_items:.1f}%)" if c.n_items else "")
            + f" comparable-n={c.comparable_n}"
        ),
        (
            f"  marginals: judge pos={c.judge_pos} neg={c.judge_neg}"
            f" | detector pos={c.det_pos} neg={c.det_neg}"
        ),
        (
            f"  confusion: tp={c.confusion['tp']} fp={c.confusion['fp']} "
            f"fn={c.confusion['fn']} tn={c.confusion['tn']}"
        ),
        (
            f"  truncation: measured {c.truncated_fresh}/{c.fresh_calls} fresh calls"
            f" | approx-stamped (export) {c.approx_truncated}/{c.n_items} items"
        ),
    ]
    if c.kappa is None:
        lines.append(f"  REFUSED — gate not evaluated: {c.refusal}")
    else:
        ci = f" 95%CI=[{c.ci[0]:.3f}, {c.ci[1]:.3f}]" if c.ci else ""
        tail = (
            " → counts toward gate (min over cells)"
            if c.counts_in_gate
            else f" (DESCRIPTIVE ONLY) — GATE NOT EVALUATED: {c.refusal}"
        )
        lines.append(f"  kappa={c.kappa:.3f}{ci} comparable-n={c.comparable_n}{tail}")
        if c.borderline:
            lines.append(f"  BORDERLINE: 95%CI straddles the {KAPPA_GATE} bar — do not read as a pass")
    return lines


def pooled_descriptive(rows: list[tuple]) -> dict:
    """Cross-stratum pooled kappa for one pair — EXPLICITLY descriptive
    (mix-dependent, estimates nothing natural; never the gate number)."""
    comp = [(j, d) for j, d, *_ in rows if j is not None]
    n = len(comp)
    k = _kappa_or_none([j for j, _ in comp], [d for _, d in comp])
    return {"n": n, "kappa": k, "note": "descriptive only — mix-dependent, never the gate"}


def gate_verdict(cells: list[CellStats], below_manifest_sample: bool = False) -> dict:
    """v2 gate: PASS/FAIL only when EVERY cell counts toward the gate;
    the gate number is the min over cell kappas. Any refusal — or a
    --limit below the manifest n — makes the gate NOT EVALUATED, which is
    never rendered or exited as a bare FAIL (ML-B6 / ADR 0009)."""
    if below_manifest_sample:
        return {
            "verdict": "not-evaluated",
            "reason": "below-manifest sample, gate not evaluated (--limit < manifest n)",
            "min_cell_kappa": None,
            "refused_cells": [],
        }
    if not cells:
        return {
            "verdict": "not-evaluated",
            "reason": "no kappa cells were produced",
            "min_cell_kappa": None,
            "refused_cells": [],
        }
    refusing = [c for c in cells if not c.counts_in_gate]
    if refusing:
        return {
            "verdict": "not-evaluated",
            "reason": "; ".join(f"{c.pair}×{c.stratum}: {c.refusal}" for c in refusing),
            "min_cell_kappa": None,
            "refused_cells": [f"{c.pair}×{c.stratum}" for c in refusing],
        }
    worst = min(c.kappa for c in cells if c.kappa is not None)
    worst_cell = next(c for c in cells if c.kappa == worst)
    verdict = "pass" if worst >= KAPPA_GATE else "fail"
    return {
        "verdict": verdict,
        "min_cell_kappa": worst,
        "min_cell": f"{worst_cell.pair}×{worst_cell.stratum}",
        "reason": (
            f"min over {len(cells)} cells at kappa>={KAPPA_GATE}, "
            f"post-exclusion n>={N_GATE} per cell"
        ),
        "refused_cells": [],
    }


__all__ = [
    "BOOTSTRAP_RESAMPLES",
    "BOOTSTRAP_SEED",
    "KAPPA_GATE",
    "MAX_EXCLUSION_SHARE",
    "N_GATE",
    "STRATA",
    "CellStats",
    "agreement_rate",
    "bootstrap_kappa_ci",
    "cell_stats",
    "cohen_kappa",
    "gate",
    "gate_verdict",
    "pooled_descriptive",
    "render_cell",
]
