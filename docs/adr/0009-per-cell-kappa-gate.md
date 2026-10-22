# 0009 — Per-pair per-stratum kappa; min-over-cells gate; CI honesty

Date: 2026-10-22
Status: Accepted

## Context
A pooled kappa across differently-weighted strata estimates nothing natural; small n makes any point estimate noise-dominated; degenerate marginals can print a misleading 0.0 sentinel.

## Decision
`pulse agreement` v2 reports kappa per comparable pair per stratum (4 cells); the gate number is the min over cells at kappa>=0.6. Every cell prints its distribution block (n, per-rater marginals, confusion cells, abstain rate, post-exclusion n, bootstrap 95% CI) BEFORE any kappa; kappa is refused on degenerate labels ('gate not evaluated'), and CI straddling the bar is labeled BORDERLINE. Pooled kappa may appear only as a labeled descriptive line. Scott's pi remains derivable from printed marginals.

## Consequences
Output text is part of the product and is locked by golden-output tests. Published claims must carry CIs and cell structure — a single number without distribution is a formatting error.
