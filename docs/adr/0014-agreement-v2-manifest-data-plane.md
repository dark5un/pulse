# 0014 — `pulse agreement` v2 consumes the run manifest; the unroll-trace gate path is replaced

Date: 2026-10-22
Status: Accepted

## Context
The gate's "pinned corpus" promise was unsatisfiable through the old
unroll-trace plane (textless TIMELINE entries, live-DB membership). CW-1/CW-2
produced Pulse-owned hashed redacted snapshots + stratified selection
manifests, and CW-3/CW-4 pinned the verdict schema v2 and the loud-failure
contract. The gate command must now run on that plane or the whole stage-1
claim is hollow. Keeping both planes flag-coaxed doubles the surface for a
pre-1.0 tool.

## Decision
`pulse agreement` v2 takes `--manifest` (required): membership is the
manifest's item list, frozen at selection; every snapshot's file sha256 is
verified against the manifest BEFORE any judge call; missing snapshots fail
loudly with "K of N missing; re-run pulse corpus export"; a sha mismatch is
an integrity failure (a re-pin is a new manifest, never an edit). The
manifest's `prompt_version` must match the build. Detector labels are always
recomputed at run time via `extract_signals` on snapshot messages (ML-B7) —
the snapshot advisory sidecar never feeds kappa; items the detector skips at
run time are excluded loudly and cost no judge call. Judge identity falls
back CLI flag -> manifest `judge` record (model, base_url, context_window —
the manifest field joins the ADR 0013 explicit tier). The old unroll-trace
gate path is REPLACED, not flag-coaxed: acceptable pre-1.0,
CHANGELOG-documented at release.

## Consequences
The gate exercises the production data plane (full redacted transcripts) on
a content-addressed frozen corpus; a rerun after failure resumes from the
finding-aware verdict cache keyed by snapshot bytes + prompt version.
`--limit` below the manifest n is allowed only as a labeled dry-run aid
("below-manifest sample, gate not evaluated").
