"""CW-5b reporting layer: per-pair-per-stratum cells, refusal rules,
bootstrap CIs, gate semantics. Pure + offline; the rendered refusal text
and distribution block ARE the product (golden-output tests)."""

import pytest

from pulse.agreement import (
    KAPPA_GATE,
    MAX_EXCLUSION_SHARE,
    CellStats,
    bootstrap_kappa_ci,
    cell_stats,
    cohen_kappa,
    gate_verdict,
    pooled_descriptive,
    render_cell,
)


def rows(pairs, approx=(), trunc=()):
    """pairs: list of (judge|None, det). approx/trunc: index sets."""
    return [
        (j, d, i in approx, (i in trunc) if j is not None else None)
        for i, (j, d) in enumerate(pairs)
    ]


# ── degenerate-label refusal: the pe=1 sentinel must NEVER reach the gate ──


def test_all_negative_cell_refuses_kappa_ml_b6():
    """September redux guard: both raters all-negative -> REFUSED, kappa
    None; the cohen_kappa 0.0 sentinel must not surface as a value."""
    c = cell_stats("correction_chain", "core", rows([(0, 0)] * 9))
    assert c.kappa is None
    assert c.counts_in_gate is False
    assert "degenerate labels" in c.refusal
    assert "judge produced 0 positives" in c.refusal
    assert "detector produced 0 positives" in c.refusal
    text = "\n".join(render_cell(c))
    assert "REFUSED — gate not evaluated" in text
    # the sentinel value is never printed as a kappa (the September quote
    # inside the refusal REASON names it — that is the point of refusing)
    assert not any(line.lstrip().startswith("kappa=") for line in text.splitlines())
    assert "pe=1 base-rate collapse" in text


def test_single_class_judge_cell_refuses():
    c = cell_stats("premature_stop", "enriched", rows([(1, 1), (1, 0), (1, 1)]))
    assert c.kappa is None
    assert "judge produced 0 negatives" in c.refusal


def test_zero_positive_sentinel_never_reaches_gate_verdict_as_fail():
    """ML-B6 end-to-end: a degenerate cell beside good cells yields
    NOT-EVALUATED, never a bare FAIL built on the 0.0 sentinel."""
    deg = cell_stats("correction_chain", "core", rows([(0, 0)] * 60))
    good = [
        cell_stats("correction_chain", "enriched", rows([(1, 1), (0, 0)] * 30)),
        cell_stats("premature_stop", "core", rows([(1, 1), (0, 0)] * 30)),
        cell_stats("premature_stop", "enriched", rows([(1, 1), (0, 0)] * 30)),
    ]
    v = gate_verdict([deg] + good)
    assert v["verdict"] == "not-evaluated"
    assert v["min_cell_kappa"] is None
    assert v["refused_cells"] == ["correction_chain×core"]


# ── abstention handling ───────────────────────────────────────────────────


def test_abstain_excluded_from_own_cell_only():
    data = [(None, 1), (1, 1), (0, 0), (0, 0)]
    c = cell_stats("correction_chain", "core", rows(data))
    assert c.abstained == 1 and c.comparable_n == 3
    assert c.confusion == {"tp": 1, "fp": 0, "fn": 0, "tn": 2}


def test_exclusion_share_guard_provisional():
    """ABSTAIN_EXCLUSION_SHARE (~25-30%) provisional knob: above it the
    cell is 'not evaluated — exclusion share too high' (MNAR, ML-A3)."""
    assert MAX_EXCLUSION_SHARE == 0.30  # flagged for user confirmation (G4)
    over = cell_stats("correction_chain", "core", rows([(None, 0)] * 4 + [(0, 0), (1, 1)] * 3))
    assert over.abstained == 4 and over.n_items == 10
    assert "exclusion share too high (40.0%" in over.refusal
    assert over.kappa is None
    under = cell_stats("correction_chain", "core", rows([(None, 0)] * 3 + [(0, 0), (1, 1)] * 4))
    assert under.refusal and "post-exclusion n" in under.refusal  # only the n floor now
    assert under.kappa is not None  # kappa printable, descriptively


def test_empty_cell_refuses_no_items():
    c = cell_stats("premature_stop", "enriched", [])
    assert "no items in stratum" in c.refusal
    assert c.kappa is None


def test_all_abstained_refuses_before_degenerate():
    c = cell_stats("correction_chain", "core", rows([(None, 0)] * 5))
    assert "abstention excluded every item" in c.refusal


# ── bootstrap CIs (ML-B1) ─────────────────────────────────────────────────


def test_bootstrap_ci_reproducible_and_bracketing():
    ja = [1, 1, 1, 0, 0, 1, 0, 0, 1, 0]
    da = [1, 0, 1, 0, 1, 1, 0, 0, 1, 0]
    ci1 = bootstrap_kappa_ci(ja, da)
    ci2 = bootstrap_kappa_ci(ja, da)
    assert ci1 is not None and ci1 == ci2  # seeded, deterministic
    k = cohen_kappa(ja, da)
    assert ci1[0] <= k <= ci1[1]


def test_bootstrap_ci_drops_undefined_resamples():
    assert bootstrap_kappa_ci([1, 1], [1, 1]) is None  # every draw pe=1
    assert bootstrap_kappa_ci([], []) is None


def test_borderline_when_ci_straddles_bar():
    """kappa exactly 0.600 at n=50 (SE ~0.11): CI straddles the bar ->
    BORDERLINE, and the cell still counts toward the gate (kappa>=0.6)."""
    data = [(1, 1)] * 20 + [(0, 0)] * 20 + [(0, 1)] * 5 + [(1, 0)] * 5
    c = cell_stats("correction_chain", "core", rows(data))
    assert c.kappa == pytest.approx(0.6)
    assert c.counts_in_gate
    assert c.ci is not None and c.ci[0] < KAPPA_GATE <= c.ci[1]
    assert c.borderline
    text = "\n".join(render_cell(c))
    assert "BORDERLINE: 95%CI straddles the 0.6 bar" in text


def test_descriptive_kappa_below_per_stratum_n_floor():
    c = cell_stats("correction_chain", "core", rows([(1, 1), (0, 0), (1, 0), (0, 1)]))
    assert c.kappa is not None and c.ci is not None
    assert not c.counts_in_gate
    assert "below per-stratum floor 50" in c.refusal
    text = "\n".join(render_cell(c))
    assert "DESCRIPTIVE ONLY" in text and "GATE NOT EVALUATED" in text


# ── gate verdict semantics (ADR 0009) ────────────────────────────────────


def _perfect(n):
    return cell_stats("p", "s", rows([(1, 1), (0, 0)] * n))


def test_gate_verdict_pass_fail_and_below_manifest():
    cells = [_perfect(30) for _ in range(4)]
    assert gate_verdict(cells)["verdict"] == "pass"
    low = cell_stats(
        "correction_chain", "core", rows([(1, 1)] * 10 + [(0, 0)] * 26 + [(1, 0), (0, 1)] * 8)
    )
    v = gate_verdict([low] + [_perfect(30) for _ in range(3)])
    assert v["verdict"] == "fail" and v["min_cell_kappa"] == low.kappa
    assert gate_verdict(cells, below_manifest_sample=True)["verdict"] == "not-evaluated"
    assert gate_verdict([])["verdict"] == "not-evaluated"


def test_pooled_kappa_is_descriptive_only():
    mixed = rows([(1, 1), (0, 0)] * 20 + [(0, 1)] * 5)
    p = pooled_descriptive(mixed)
    assert p["kappa"] is not None and "descriptive" in p["note"]
    deg = pooled_descriptive(rows([(0, 0)] * 9))
    assert deg["kappa"] is None  # never the 0.0 sentinel


# ── golden output: the distribution block + refusal text are the product ──

GOLDEN_DEGENERATE_CELL = [
    "── kappa cell: premature_stop × core " + "─" * 12,
    "  items=9 abstained=1 (11.1%) comparable-n=8",
    "  marginals: judge pos=0 neg=8 | detector pos=0 neg=8",
    "  confusion: tp=0 fp=0 fn=0 tn=8",
    "  truncation: measured 2/8 fresh calls | approx-stamped (export) 7/9 items",
    (
        "  REFUSED — gate not evaluated: degenerate labels (judge produced 0 positives; "
        "detector produced 0 positives) — the pe=1 base-rate collapse behind September's "
        "'kappa=0.0 / agree=1.0': it would measure the corpus, not the judge"
    ),
]


def test_golden_distribution_block_and_refusal_text():
    data = [(0, 0)] * 8 + [(None, 0)]
    c = cell_stats("premature_stop", "core", rows(data, approx={0, 1, 2, 3, 4, 5, 6}, trunc={1, 5}))
    assert render_cell(c) == GOLDEN_DEGENERATE_CELL


def test_golden_counts_in_distribution_block():
    """n, per-rater marginals, confusion cells, abstain rate,
    post-exclusion n, truncation rate — ALL before any kappa line."""
    c = cell_stats(
        "correction_chain",
        "enriched",
        rows(
            [(1, 1), (0, 0), (None, 0), (1, 0)] * 15,
            approx={i for i in range(60) if i % 4 in (0, 3)},
            trunc={0},
        ),
    )
    block = render_cell(c)
    assert block[1] == "  items=60 abstained=15 (25.0%) comparable-n=45"
    assert block[2] == "  marginals: judge pos=30 neg=15 | detector pos=15 neg=30"
    assert block[3] == "  confusion: tp=15 fp=0 fn=15 tn=15"
    assert block[4] == "  truncation: measured 1/45 fresh calls | approx-stamped (export) 30/60 items"
    assert block[5].startswith("  kappa=0.400")  # legitimate 0.4 (pe<1) vs refusal (pe=1)
    assert "DESCRIPTIVE ONLY" in block[5]


@pytest.mark.parametrize(
    "cell,expected",
    [
        (cell_stats("correction_chain", "core", []), 2),
        (cell_stats("correction_chain", "core", rows([(0, 0)] * 60)), 2),
    ],
)
def test_refusal_shape_is_cellstats(cell: CellStats, expected: int):
    assert not cell.counts_in_gate
    assert cell.kappa is None
