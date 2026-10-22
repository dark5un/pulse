# 0010 — Model-derived judge prompt budget replaces the fixed 12k cap

Date: 2026-10-22
Status: Accepted

## Context
MAX_PROMPT_CHARS=12,000 came from hosted-judge-era economics (per-call cost and data egress). With a local judge on large-context endpoints, ~90% of the operator's real sessions were being middle-truncated, driving abstention and MNAR skew.

## Decision
The judge prompt budget derives from the pinned endpoint's context window minus reserved headroom (instructions+schema+output). Over-long rejections by the provider fail loudly, never silently clip. Actual per-call truncation is measured at judge time and reported; the per-message 500-char cap is flagged for measurement as the next likely evidence limiter.

## Consequences
Batch wall-clock grows with window; capacity planning uses dry-run measured per-call seconds. Full-context judge QUALITY is not assumed — abstain/truncation rates are the empirical check, and the effective budget stays a measured knob, not a guess.
