# 0016 — Judge HTTP request timeout is an explicit operator knob

Date: 2026-10-22
Status: Accepted

## Context
G4's first live dry-run pass judged a 21k-char prompt in 90.5 s on the
local 1M-context production endpoint; the next (621-message, ~190k-char)
prompt exceeded the hardcoded 120 s client timeout and the run died loudly
(exit 2, cache intact — the M0 contract proved itself on real hardware).
With ADR 0010's model-derived budget, a local judge can legitimately spend
minutes per call; a fixed client timeout set in the hosted-judge era
guarantees mid-run deaths on exactly the large sessions the gate needs.

## Decision
The judge request timeout becomes `PULSE_JUDGE_TIMEOUT_S` (seconds, must
be > 0, loud on invalid values), defaulting to the previous 120 s. The
gate batch path on big-context local endpoints pins it explicitly. No
silent retry is added: a timeout stays a loud JudgeCallError and the
per-record cache flush makes the resume path the recovery mechanism.

## Consequences
CW-7's full run must set the timeout from G4's measured per-call seconds
(never keep 120 s for 100k+ char prompts). Timeout policy is recorded by
version: reruns quoting stage-1 numbers should state the knob used.
