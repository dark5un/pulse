# Changelog

All notable changes to hermes-pulse. Format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/);
versions follow [Semantic Versioning](https://semver.org/).

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
