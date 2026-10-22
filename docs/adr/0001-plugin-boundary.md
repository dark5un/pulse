# 0001 — Plugin boundary: read host state, never change it

Date: 2026-10-22
Status: Accepted

## Context
Pulse ships as a plugin inside a host harness (Hermes) plus a standalone CLI. A first idea was to enrich the host's unroll trace format so Pulse's corpus would be text-rich everywhere.

## Decision
Pulse may READ host state (session store via `session_store`, the host model lane via `ctx.llm.complete_structured`) but must never change host behavior, host calls, or host-owned formats. The unroll format change was rejected; Pulse owns its own snapshot format instead.

## Consequences
All corpus/tooling features must be implementable inside the Pulse repo. Host upgrades cannot silently break Pulse assumptions beyond read-schema drift, which the integration harness must catch.
