# 0002 — Staged validation of the deep LLM judge

Date: 2026-10-22
Status: Accepted

## Context
The `--deep` LLM judge emits four verdicts but all are labeled provisional; an agreement gate (Cohen's kappa vs deterministic detectors, kappa>=0.6) exists to license claims. The first real gate run failed degenerately (textless corpus, all-negative labels).

## Decision
Stage the validation: (1) fix the deterministic-plane plumbing and run a real agreement gate as a SMOKE TEST — judge-vs-detector kappa where the detector itself is provisional proves nothing about judge quality; (2) anchor the real claim on human gold labels (stage 2, separate design). Stage-1 PASS licenses only: plane validated, non-degenerate corpus, detector-adjacent agreement. It licenses no judge-quality claim and no deep-signal weight promotion.

## Consequences
Deep-signal weights stay provisional until stage 2. README claims must state the boundary verbatim. Kappa ceiling issues from construct non-equivalence are expected and documented, not hidden.
