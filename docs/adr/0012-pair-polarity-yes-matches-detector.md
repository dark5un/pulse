# 0012 — Pair polarity: judge finding=yes pairs with detector-present; absent = abstain

Date: 2026-10-22
Status: Accepted

## Context
The gate's two comparable pairs map judge signals to deterministic
detector signals, but the repo contradicted itself: the agreement
module's docstring said the correction pair was
`finding=NO <-> correction_chain present`, while the batch label mapping
used judge-positive (penalty>0, i.e. finding=yes) <-> detector-present.
The v2 prompt is explicit that "'yes' means the PROBLEM was found", and
the detectors fire when the same problem occurs (correction_chain =
repeated user corrections — a correction-quality problem instance;
premature_stop = agent offering to stop mid-task — a goal-completion
problem instance). An inverted pair makes a good judge trend kappa
NEGATIVE — the September failure redux waiting to happen.

## Decision
Chosen direction: **judge finding=yes (penalty>0) <-> detector signal
present** (positive<->positive), for both pairs. finding=no is
judge-negative (0). `unscoreable` or an ABSENT verdict for a declared
signal abstains (label None) and is excluded from that pair's kappa
only — never counted as "no". The docstring is corrected, not the code
mapping. Per-pair truth tables pin (finding, detector-presence) ->
expected confusion cell in tests, and the verdict-cache value is
finding-aware (`{signal: finding}`), keyed by prompt version so v1
name-list entries can never collide.

## Consequences
Every downstream kappa sign is now defined before any GPU time is
spent. Cache semantics change with the v2 version key (old entries age
out). Stage 2's gold-label rubric must ask the detector-side question
("is this problem present?"), matching this polarity.
