# Changelog

All notable changes to hermes-pulse. Format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/);
versions follow [Semantic Versioning](https://semver.org/).

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
