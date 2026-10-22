# 0018 — Structural detector-construct fixes: user-turn adjacency, claim-tail + continuation

Date: 2026-10-22
Status: Accepted

## Context
An aggregate calibration study (zero judge calls, published numbers only)
found the two agreement-gate anchor detectors were **structurally
unfireable on real traffic** — not mis-tuned to one user:

- `correction_chain` required 3 consecutive *raw message rows* with role
  `user`. Harnesses always reply between user turns, so user runs of
  length ≥ 3 essentially never occur: the construct fired on 0 eligible
  sessions in the studied corpus.
- `premature_stop` scanned for 6 exact stop-offering phrases that had
  **zero literal occurrences** across the whole studied corpus, and fired
  on the mere presence of a phrase with no evidence the user disagreed.

A third, subtler defect: corpus snapshots deliberately carry no
`tool_calls` (ADR 0003), but `detect_task_type` consumes them. Recomputing
signals on the snapshot plane without a task type re-detected it from the
skeleton alone and misclassified question-heavy coding sessions as
brainstorm — silently gating the pair detectors off at gate time.

## Decision
Fix the constructs (structure only, generic defaults — ADR 0017):

- `correction_chain`: adjacency moves to USER-TURN space — at least
  `CORRECTION_MIN_IN_WINDOW` (=2) correction-flagged user turns inside
  any `CORRECTION_USER_WINDOW` (=3) consecutive user turns. A turn is
  flagged if it starts with a correction word OR contains a marker from a
  generic English correction/rephrase set (contribution-extensible,
  word-boundary matched, not cherry-picked from any user's corpus).
- `premature_stop`: a completion CLAIM inside the last `CLAIM_TAIL_CHARS`
  (=200) chars of an assistant turn, followed by a user CONTINUATION
  request (generic marker set) within the next `CONTINUE_WINDOW_TURNS`
  (=2) user turns. Legacy stop-offer phrases survive only as tail-claim
  entries; the construct now requires observable user pushback.
- Both lexicons are role+content computable, so they recompute correctly
  on the snapshot plane (ML-B7).
- Snapshot-plane recomputation (`pulse agreement`, `pulse corpus select
  --stats`) uses the snapshot's **stamped** `task_type` instead of
  re-detecting from the tool_calls-less skeleton.
- Signal names, targets, severities and penalties are unchanged; the
  weights table is untouched. Genuine 3-adjacent-user-row anomalies still
  fire under the window rule (regression-tested).
- `pulse corpus select --stats`: report-only floors measurement —
  prints per-pair detector-positive pools and stratum capacities without
  writing a manifest or relaxing any bar.

## Consequences
- The gate's detector-positive pools became reachable (both ≥ the 10
  floor on the developer's reference corpus); the remaining selection
  shortfall (corpus size vs n≥50 per stratum) stays a data-availability
  question for each install, not a reason to keep dead detectors.
- Session scores shift slightly where the corrected constructs now fire
  that never could before — expected for a bug fix; redteam TRACKED
  signal accounting is unaffected.
- Lexicons stay generic: per-user fit comes from each install's own
  corpus gate (ADR 0017), never from tuning shipped constants to one
  operator's transcripts.
- Aggregate-only evidence; no transcript-derived data in the study,
  this ADR, or `--stats` output (ADR 0011).
