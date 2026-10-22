# 0005 — Gate exercises two judge paths: pinned API + in-host lane

Date: 2026-10-22
Status: Accepted

## Context
Production `/pulse deep` judges via the host's `ctx.llm` lane; a batch agreement run historically used a separate OpenAI-compatible client. Validating only the CLI path had already produced a gate that tested the wrong judge.

## Decision
Both are first-class: batch agreement runs over the pinned local endpoint (same model class as production, recorded model+checkpoint+base_url), and `/pulse gatecheck N` runs a seeded subset through the real in-host `ctx.llm` lane, sharing the on-disk verdict cache so the spot-check is nearly free after a batch run.

## Consequences
Two code paths to keep in sync behind one `JudgeBackend` seam and one prompt builder/parser. The via-host row is always marked lane=via-host in the manifest.
