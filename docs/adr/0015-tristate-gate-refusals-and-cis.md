# 0015 — Tri-state gate verdict; per-cell refusal rules and bootstrap CIs

Date: 2026-10-22
Status: Accepted

## Context
A degenerate cell (either rater single-class) makes Cohen's kappa
undefined-to-meaningless: the pe=1 -> 0.0 sentinel in the old single-number
gate turned "the corpus has no positives" into a bare gate FAIL — September's
base-rate collapse re-run. A pooled cross-stratum kappa depends on the mix
ratio and estimates nothing natural. At stage-1 n, SEs are large enough
that a point estimate near the bar is noise.

## Decision
`pulse agreement` v2 reports kappa per comparable pair per stratum (4
cells); every cell prints a distribution block (n, per-rater marginals,
confusion cells, abstain rate, post-exclusion n, per-stratum truncation
rates) BEFORE any kappa line. A cell REFUSES kappa — "gate not evaluated" —
on: no items, full abstention, an abstain share above the provisional
30% exclusion guard (MNAR; flagged for operator confirmation before the
full run), or degenerate marginals (the pe=1 sentinel can never reach the
gate — ML-B6). Post-exclusion n below the per-stratum floor (50) keeps
kappa as a labeled DESCRIPTIVE value but the cell never counts toward the
gate. Every printed kappa carries a bootstrap 95% CI (stdlib random,
1000 item resamples, fixed seed string so reruns reproduce bounds); CI
straddling the 0.6 bar is labeled BORDERLINE. Pooled kappa is an
explicitly-labeled descriptive line only. The gate verdict is tri-state:
PASS (all cells count, min-over-cells >= 0.6, exit 0), FAIL (all cells
count, min < 0.6, exit 1), NOT EVALUATED (any refusal or a below-manifest
sample; exit 2 — the same exit code as run failure, distinguished by the
printed verdict line; a refusal is never a FAIL). The rendered refusal
text and distribution blocks are locked by golden-output tests.

## Consequences
Output text is product: honesty refusals are first-class outcomes, and a
"gate not evaluated" run with zero detector positives is a PASS-shaped
honest result, not a failure to hide. Stage-2 comparisons must quote the
same bars, guard value, and bootstrap seed; changing them bumps the report
version.
