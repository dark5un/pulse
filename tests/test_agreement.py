"""Tests for judge-vs-deterministic agreement (B2, task J4). Pure + offline."""

from pulse.agreement import agreement_rate, cohen_kappa


def test_kappa_perfect_agreement():
    assert cohen_kappa([1, 1, 0, 0], [1, 1, 0, 0]) == 1.0


def test_kappa_chance_level_near_zero():
    assert abs(cohen_kappa([1, 0, 1, 0], [1, 1, 0, 0])) < 0.3


def test_kappa_empty():
    assert cohen_kappa([], []) == 0.0


def test_kappa_single_class():
    # No variance -> undefined; report 0.0, never fabricate.
    assert cohen_kappa([1, 1, 1], [1, 1, 1]) == 0.0


def test_agreement_rate_counts_matches():
    out = agreement_rate([1, 0, 1], [1, 1, 1])
    assert out["rate"] == round(2 / 3, 3)
    assert out["n"] == 3
    assert out["confusion"] == {"tp": 2, "tn": 0, "fp": 1, "fn": 0}
