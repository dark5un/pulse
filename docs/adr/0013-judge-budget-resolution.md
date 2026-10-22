# 0013 — Judge budget mechanics: resolution order, /v1/models probe, explicit fallbacks

Date: 2026-10-22
Status: Accepted (implementation detail of ADR 0010)

## Context
ADR 0010 replaced the fixed 12k prompt cap with a model-derived budget but
left the mechanics open: where the context window comes from, what happens
when it can't be known, and how headroom is reserved.

## Decision
Resolution order, first hit wins, each with a recorded `source`:
(1) explicit context-window argument (CLI `--judge-context` / run-manifest
`judge.context_window`), (2) `PULSE_JUDGE_CONTEXT` env (tokens), (3) a
read-only GET probe of the pinned endpoint's `/v1/models` metadata
(llama.cpp-style `n_ctx`/`num_ctx`/`context_window`/`max_context_length`
keys; never any service lifecycle action, per ADR 0007), (4) explicit
char-level config `PULSE_JUDGE_MAX_PROMPT_CHARS`. If none exist, the batch
gate raises loudly naming the knobs — it never assumes a window. Derived
budget = (context tokens − reserve) × 4 chars/token with reserve defaulting
to 1536 tokens (output + instructions/schema + estimation slack,
overridable via `PULSE_JUDGE_RESERVE_TOKENS`); the token/char conversion is
an estimate, so the actual per-call prompt size + truncated flag is
measured at judge time (`JudgeRun`) and reported, and a provider rejection
of an over-long prompt raises instead of silently clipping. Middle
truncation stays the disclosed fallback path. `MAX_PROMPT_CHARS` (12k)
survives only as the *stated* static fallback for interactive paths with
no endpoint to probe; its source is printed. The per-message
`MAX_MESSAGE_CHARS=500` cap is untouched here but stays flagged for the
stage-1 run's measurement (it is the likely evidence limiter for
tool-heavy sessions).

## Consequences
Run manifests pin the window alongside model identity, so reruns and
stage-2 comparisons quote the same budget. Batch wall-clock grows with the
window; G4 measures per-call seconds for CW-7 planning. A context-blind
endpoint (no metadata) is not silently judged at 12k — the operator names
the window explicitly.
