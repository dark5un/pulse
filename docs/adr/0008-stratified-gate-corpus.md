# 0008 — Stratified gate corpus with positives floors

Date: 2026-10-22
Status: Accepted

## Context
Real session corpora are dominated by uneventful sessions; an all-negative corpus collapses kappa (pe=1 -> undefined; observed as 'kappa=0.0/agree=1.0'). Pure signal-enrichment would only ever ask the judge where the detector already looked.

## Decision
Corpus = random core (generalization read) + signal-enriched half (guarantees per-pair positives), with provisional floors >=10 detector-positive AND >=10 judge-positive per pair, n>=50 per stratum. If real data cannot meet eligibility/floors, that is escalated to the user — bars are not relaxed silently.

## Consequences
Selection is reproducible (seeded, stratum-labeled in the manifest). Enriched sessions are longer, which interacts with windowing (see 0010) — hence per-stratum truncation and abstain rates in every report.
