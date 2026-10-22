# 0011 — Conversation data is private by default; aggregates only in public

Date: 2026-10-22
Status: Accepted

## Context
Pulse's corpus is derived from the operator's real AI conversations. Even redacted snapshots and session identifiers are private material.

## Decision
Nothing transcript-derived (raw or redacted text, snapshots, session ids, content hashes, metadata) enters public artifacts, remotes, web pages, or third-party services. Public outputs are aggregate-only (counts, kappa cells, rates) and require explicit user approval. Run manifests with per-session identifiers stay local; a public receipt uses leaderboard-style anonymization (truncated salted hashes) if used at all.

## Consequences
Corpora live in gitignored directories; CI and tests run on synthetic fixtures only. Every review/claim cycle checks this boundary before publication.
