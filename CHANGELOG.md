# Changelog

All notable changes to hermes-pulse. Format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/);
versions follow [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Fixed

- Deep-mode persistence (PU-4): every `/pulse deep` exit now writes exactly
  one row — `deep_unavailable` (host LLM lane missing), `deep_failed`
  (judge raised), `deep_success` — so no analysis vanishes from
  trends/models. Previously only the success path persisted.
- Session-bound feedback (PU-5): `useful`/`not-useful`/`yes`/`no` bind to
  the session just analyzed (`_CURRENT_SESSION_ID`), never to a global
  `ORDER BY run_at DESC LIMIT 1` row — concurrent sessions can no longer
  cross-rate. Rating a session with no analysis reports that explicitly.
- Typed session-DB errors (PU-8): `load_session()` raises
  `SchemaIncompatibleError` for valid-SQLite-but-wrong-schema files,
  distinct from missing DB (empty) and from empty DB; the CLI exits 2 with
  the cause, the plugin treats it as no-session.
- Strict JSONL (PU-9): malformed lines fail with exit 1, line numbers and a
  count; `--best-effort` opts into skipping, and `--json` carries
  `malformed_lines`.
- Trace loader hardening (PU-2): new `TraceSchemaError(ValueError)` naming
  the offending field — `COST`/`USAGE`/`STATE_GRAPH`/`DEPENDENCIES` must be
  mappings, `TIMELINE` a list of mappings, skills/tags string lists,
  `cost_usd` finite numeric. Files over `MAX_TRACE_BYTES` (8 MiB) and
  literals over `MAX_AST_NODES` nodes / `MAX_LITERAL_DEPTH` depth are
  rejected before `literal_eval`. Falsy-but-wrong values (`COST = 1.0`,
  `TIMELINE = 1`) can no longer slip through `or {}` defaults.
- Judge verdict validation (PU-3): `parse_verdict_text()` now returns a
  `VerdictParseResult(signals, diagnostics)` — finding must be `yes`/`no`
  (`no` with penalty is dropped), penalties must be finite, `penalty > 0`
  needs non-empty bounded evidence, duplicate signals merge deterministically
  (highest penalty wins, diagnostic emitted), evidence must be a bounded
  list of bounded strings. No invalid verdict can carry a penalty into
  scoring; `detect_deep()` still returns a plain signal list.
- `__main__.py`: hoist `bundle = None` and narrow before use (Pyright-clean
  without suppression).
- `pulse verify` no longer executes the trace: the `subprocess.run` call is
  deleted and verification is a structural inspect (parses via the safe AST
  loader, required constants present, sha256 matches `run-manifest.json`,
  rescore matches the pinned sidecar). Result schema is now
  `{"loads", "hash_matches", "score_reproduces", "detail"}` (artifact
  schema v2); the old `replays` ("script exited 0") key is removed. If
  executing replay is ever wanted, it belongs in an explicit opt-in replay
  path — never inside `verify`.
- Run manifests now pin the real package version: `_pulse_version()` falls
  back to `pulse.__version__` (single source of truth, matching
  `pyproject.toml`) instead of recording `"dev"` when distribution metadata
  is unavailable (editable checkout, isolated tool install).

## [0.6.0] - 2026-09-05

### Added

- `/pulse deep` slash command (host `ctx.llm` lane — reuses the live Hermes
  model connection, no keys): deterministic analysis + one temperature-0
  JSON-mode judge call; verdicts land on the card with model, tokens,
  elapsed; persists `run_mode='deep'`. Judge failure is loud (error string +
  deterministic card), never silent.
- Cost honesty for deep runs: dollars from Hermes alone (`cost_usd` when the
  harness reports it → `~$X (cost from Hermes)`); otherwise the card states
  "Hermes reported no dollar cost; tokens are enough". No local price table,
  nothing estimated, nothing to go stale.
- `--deep` LLM-judge mode (B2, provisional until agreement-gated): one
  combined temperature-0 call per session via stdlib `urllib` (no new
  deps); four verdicts become normal `Signal`s — `goal_completion`,
  `context_retention`, `correction_quality` (user-targeted),
  `hallucination`. Config `PULSE_API_KEY` → `OPENAI_API_KEY` →
  `HERMES_API_KEY` → `~/.hermes/.env`, model `PULSE_JUDGE_MODEL`,
  base URL `PULSE_JUDGE_BASE_URL`. Unparseable output yields zero signals;
  judge failure exits 1, never silent. `score_bundle` accepts
  `extra_signals` + `deep` (deterministic sidecars byte-identical).
- `pulse agreement` — judge-vs-deterministic Cohen's kappa on the
  comparable pairs plus a verdict cache (trace-hash + prompt-version keyed).
  PASS needs kappa ≥ 0.6 at n ≥ 50. First real-key run (2026-09-05,
  `openai/gpt-4o-mini` via OpenRouter, local 10-trace corpus): judge returned
  zero verdicts on all 10 traces (empty verdict lists — thin textless
  TIMELINEs give the judge nothing to grade), so kappa=0.0/agree=1.0 on both
  pairs and the gate correctly reports FAIL (pending). Numbers published as
  measured; gate needs n ≥ 50 rich sessions before any hosted-judge claim.
- Capture-side session tags (C2-a): set `UNROLL_SESSION_TAGS="team-a,feat-x"`
  (`HERMES_SESSION_TAGS` legacy fallback) — unroll writes a `SESSION_TAGS`
  constant, sidecars carry `session_tags`, `pulse costs --group-by tag`
  attributes with no registry CSV (`untagged` when empty).

## [0.4.0] - 2026-09-05

### Added

- Scenario-coverage commands (all standalone — plain trace dirs in/out):
  - `pulse replay` — corpus fan-out runner (same-interpreter subprocess,
    per-trace timeout, PASS/FAIL/TIMEOUT table, exit 0/1; `--live`
    passes through to the trace replayer).
  - `pulse compare --a DIR --b DIR` — score distributions
    (mean/median/p25/p75, cost + timing deltas, plain-English verdict
    labeled provisional with N).
  - `pulse skills` — per-skill ROI ledger (loads, deadweight/correction
    rates, mean cost, task-type mix, skill-less baseline; correlation,
    not causation).
  - `pulse export` — SFT + DPO pairs (`sharegpt|jsonl`, `--min-score`,
    per-file redaction receipts in `manifest.json`, `--review`
    spot-check mode for mined pairs).
  - `pulse experiment` — run manifests (variable, versions, timestamp,
    trace hashes); `pulse bundle/verify` — self-contained
    `<session>.artifact/` + replay/rescore check.
  - `pulse incident` — 3am postmortem skeleton (window, before/after
    scores, counterfactual commands); `pulse flake` — dry-run divergence
    map (per-step stability, diverging indices).
  - `pulse costs --join sessions.csv` — join-side team attribution
    (totals, per-task split, `unmapped` bucket; no capture change).
  - `pulse leaderboard --task/--top` — onboarding curation filters.

## [0.3.0] - 2026-09-05

### Added

- Session gym workflows (all standalone — needs no Hermes install, just
  `pip install hermes-pulse` + a directory of trace files):
  - `pulse leaderboard` — top/bottom 3 traces per task type over corpus
    sidecars (live-scores traces missing a sidecar), anonymized IDs,
    ties break toward lower cost (`src/pulse/leaderboard.py`,
    `src/pulse/leaderboard_cli.py`).
  - Quality gate — `src/pulse/gate.py::compare` (per-task mean vs
    tolerance) + `scripts/pulse_gate.py` wrapper (exit 0/1, delta table)
    with a copy-paste GitHub Actions recipe in the README.
  - Red-team calmness — `scripts/redteam/prompts.md` (12 prompts, 4
    adversarial categories) + `src/pulse/redteam.py::calmness` (mean
    score, frustration/correction/reasoning rates per 10 sessions,
    calmest first) + `scripts/redteam_score.py`.
  - Skill portability — `src/pulse/portability.py` verdicts
    (`portable` / `model_specific` / `dead`) + `pulse portability` CLI.
- Shared scorer `src/pulse/trace_score.py` (`score_bundle`,
  `score_trace_file`, `anonymize`); `scripts/build_corpus.py` is now a
  thin wrapper. Sidecars gain `active_skills` (rescore old corpora with
  `scripts/build_corpus.py`); downstream tools never re-parse a trace
  file when its sidecar exists.

## [0.2.0] - 2026-09-05

### Added

- `pulse --unroll <trace.py>` mode: safe AST trace loader
  (`src/pulse/unroll_loader.py`, never executes trace files) converting
  TIMELINE into Pulse messages, with trace metadata in `--json` output.
- Three unroll-native detectors (`src/pulse/signals_unroll.py`, all
  thresholds provisional until ~100-session calibration):
  `latency_regression` (step `duration_ms > 5000`),
  `cost_anomaly` (brainstorm > $0.50, coding > $5.00),
  `skill_deadweight` (ACTIVE_SKILLS entry with zero `tool_call` steps).
- Session gym: `scripts/build_corpus.py` keeps bottom-10 scored traces
  with sidecar JSON; weekly Monday-09:00 digest cron rescores and reports
  worst session, total cost, top recurring signal.
