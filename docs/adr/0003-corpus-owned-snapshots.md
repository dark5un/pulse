# 0003 — Corpus = Pulse-owned hashed snapshots, redacted at write

Date: 2026-10-22
Status: Accepted

## Context
Gate corpora could be live-DB queries or file snapshots. The gate's 'pinned corpus' promise requires immutability; a live session DB is prunable and machine-local. Snapshotting transcript text to disk creates a new sensitive artifact class.

## Decision
`pulse corpus export` writes one JSON snapshot per session in Pulse's own schema, filename keyed by sha256(content), with secrets redacted AT WRITE TIME by the same redactor that guards the judge prompt (pattern set versioned as REDACT_VERSION, stamped in every file and in run manifests). Incremental: unchanged content hash = skip.

## Consequences
Corpus dirs are never git-tracked and are treated as private data (see 0011). Cache keys over file bytes stay stable under redaction-regex changes because the bytes themselves change — redaction vintage stays auditable. Export-time `approx_truncated` flags are advisory only (see 0010).
