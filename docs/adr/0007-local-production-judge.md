# 0007 — Judge model = local production model; service lifecycle is user-only

Date: 2026-10-22
Status: Accepted

## Context
The gate must validate the judge production actually uses. Production `/pulse deep` runs on the host's active model — locally served on the operator's own GPU. Earlier attempts used a hosted API model.

## Decision
Stage 1 measures the local production model as the primary judge row (optional secondary row also local). Execution is strictly serial against an already-live endpoint: the agent never starts, stops, toggles, or switches model services, and never runs concurrent judge streams.

## Consequences
No transcript egress to third parties; judge cost becomes wall-clock capacity, planned from measured per-call seconds at the dry run. Numbers pin model identity (name, checkpoint/version from /v1/models when exposed, context window).
