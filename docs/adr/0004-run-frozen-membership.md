# 0004 — Run-frozen corpus membership via run manifests

Date: 2026-10-22
Status: Accepted

## Context
Sessions grow after being snapshotted ('revisited'). A corpus that tracks the latest content makes the gate measure a moving target; two runs weeks apart would silently be different tests.

## Decision
A gate run consumes an explicit manifest (corpus hashes, selection seed, stratum labels, judge identity, PROMPT_VERSION, redact_version, context window, timestamp). Membership is frozen per run; revisits produce new snapshot files under new hashes, but a re-pin is a deliberate new manifest, never an edit. Selection dedupes by session id (newest hash wins) to avoid double-counting one session.

## Consequences
Kappa history stays comparable across prompt-version bumps: each number names its pinned hash set. Storage grows monotonically; superseded snapshots are reportable via `pulse corpus list`.
