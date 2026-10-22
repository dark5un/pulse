# 0006 — Per-signal `unscoreable` abstain verdicts

Date: 2026-10-22
Status: Accepted

## Context
Binary yes/no forced-choice verdicts are biased when the judge is shown a thin or truncated transcript (rating-indeterminacy literature, e.g. arXiv 2503.05965); the first gate failure was aggravated by a judge forced to opine on skeleton data.

## Decision
Verdict findings become `yes | no | unscoreable` per signal (PROMPT_VERSION v2). Abstained items are excluded from that pair's kappa only; per-signal, per-stratum abstain rates are reported as corpus-suitability readouts. An ABSENT verdict for a declared signal counts as abstain, never as 'no'. Cells whose exclusion share passes a provisional ~25-30% are labeled 'not evaluated' rather than measured.

## Consequences
Old v1 cache entries age out via version keys. Judge dodging becomes visible data (abstain rate) instead of invisible noise. Stage 2 may replace the anchor but keeps the elicitation contract.
