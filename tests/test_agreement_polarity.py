"""[ML-A1] PAIR POLARITY — pinned truth tables (ADR 0012).

The v2 prompt defines finding="yes" as "the PROBLEM was found". The
deterministic detectors (signals.py) fire when the same problem occurs:
correction_chain = repeated user corrections (a correction-quality
problem instance); premature_stop = agent offering to stop mid-task (a
goal-completion problem instance). Therefore the ONLY non-inverted pair
mapping is: judge finding=yes <-> detector present (both label 1),
finding=no <-> label 0, and unscoreable/absent -> abstain (None, excluded
from that pair's kappa only). September's agreement.py docstring claimed
finding=NO <-> correction_chain present — inverted; an inverted pair makes
a GOOD judge trend kappa NEGATIVE. These tables pin the corrected
direction for code + docstring + tests.
"""

import pytest

from pulse.agreement import agreement_rate, cohen_kappa
from pulse.agreement_cli import _labels_from_findings, _pair_label


# ── (finding, detector-presence) -> expected judge label ─────────────────
@pytest.mark.parametrize(
    "finding,expected",
    [
        ("yes", 1),  # problem found  -> judge positive
        ("no", 0),  # checked, absent -> judge negative
        ("unscoreable", None),  # explicit abstain
        (None, None),  # ABSENT verdict -> abstain, never "no" (ADR 0006)
        ("garbage", None),  # anything else can never vote
    ],
)
def test_pair_label_finding_to_label(finding, expected):
    assert _pair_label(finding) == expected


# ── (judge label, detector label) -> expected confusion cell ─────────────
@pytest.mark.parametrize(
    "judge_label,det_label,cell",
    [
        (1, 1, "tp"),  # finding=yes,   detector present  -> agree positive
        (1, 0, "fn"),  # finding=yes,   detector absent   -> judge-only hit
        (0, 1, "fp"),  # finding=no,    detector present  -> judge miss
        (0, 0, "tn"),  # finding=no,    detector absent   -> agree negative
    ],
)
@pytest.mark.parametrize(
    "pair,judge_signal",
    [
        ("correction_chain", "correction_quality"),
        ("premature_stop", "goal_completion"),
    ],
)
def test_polarity_confusion_cells(pair, judge_signal, judge_label, det_label, cell):
    # sanity: kappa on a perfect (both-positive) corpus is positive, never
    # negative — the exact failure mode of the inverted docstring polarity.
    assert cohen_kappa([judge_label], [det_label]) in (0.0, 1.0)
    conf = agreement_rate([judge_label], [det_label])["confusion"]
    assert conf[cell] == 1
    assert sum(conf.values()) == 1
    # A judge that agrees with the detector on the problem-present cell
    # must be scored positive: tp+tn, not fp+fn.
    if judge_label == det_label:
        assert conf["tp"] + conf["tn"] == 1
    else:
        assert conf["fp"] + conf["fn"] == 1


def test_findings_map_to_labels_end_to_end():
    """Full mapping through the cache-shaped findings dict."""
    labels = _labels_from_findings(
        {
            "correction_quality": "yes",
            "goal_completion": "no",
            "hallucination": "unscoreable",
            # context_retention ABSENT on purpose:
        }
    )
    assert labels["correction_chain"] == 1  # finding=yes <-> detector-present
    assert labels["premature_stop"] == 0  # finding=no  <-> detector-absent
    assert labels["_hallucination_rate"] is None  # abstain
    assert labels["_context_retention_rate"] is None  # absent = abstain


def test_good_judge_against_detector_is_positive_kappa():
    """A judge that says 'yes' exactly where the detector fires produces
    kappa 1.0 — the pinned polarity; the inverted mapping would give -1."""
    judge = [1, 1, 0, 0]  # findings: yes, yes, no, no
    det = [1, 1, 0, 0]  # correction_chain present, present, absent, absent
    assert cohen_kappa(judge, det) == 1.0


def test_absent_verdict_never_counted_as_negative():
    """Omission must not inflate the negative class (the v1 laundering)."""
    findings = {}  # judge returned nothing parseable for this session
    labels = _labels_from_findings(findings)
    for pair in ("correction_chain", "premature_stop"):
        assert labels[pair] is None
