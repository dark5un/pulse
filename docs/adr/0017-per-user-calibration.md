# 0017 — Calibration is per-user; project gate runs are developer reference runs

Date: 2026-10-22
Status: Accepted

## Context
Stage 1's corpus machinery was built on the operator's own sessions, and
early framing risked presenting those numbers as the project's global
calibration. The owner's mental model — confirmed as the product design —
is that each user calibrates on their own data. Additionally, two anchor
detectors were found structurally unfireable on ANY traffic (not
mis-tuned to one user).

## Decision
Per-user calibration IS the product: every install runs
`pulse corpus export -> select -> agreement` against its own session
store, and gate thresholds (n>=50 per stratum, kappa>=0.6) are a
per-install contract. Refusal/CI machinery makes small early corpora
honest. The operator's gate run is labeled a **developer reference run**
(plumbing validation on one machine's traffic); it calibrates nobody
else's defaults. Universal fixes go into the detectors only where the
construct is structurally broken (e.g., adjacency in user-turn space);
shipped lexicons/thresholds stay GENERIC defaults — never "fitted to the
operator's corpus." A per-user adaptation loop (gym-style guidance) may
be added later without changing this boundary.

## Consequences
- README/prose claims must say "fitted to the user's own sessions" for
  any per-install numbers, and "developer reference run, single operator"
  for the shipped gate example numbers.
- The operator's conversations never become public calibration data
  (consistent with ADR 0011); aggregate reference numbers remain
  privacy-safe.
- New users' installs start with generic defaults and accrue their own
  corpus; gate status is personal, not project-wide.
- Supersedes nothing; refines the claim boundary of ADR 0002.
