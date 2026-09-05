# Pulse — Session Health Monitor for AI Conversations

![Pulse hero](assets/pulse-hero.png)

Pulse is a harness-neutral session quality engine with native integrations for Hermes Agent and Pi. It analyzes conversations with evidence-based signals attributed to the user, agent, or system, while preserving each harness's native session and state model.

## Commands

| Command | Description |
|---|---|
| `/pulse` | Analyze the current/latest session |
| `/pulse trends` | Show the latest 20 analyses |
| `/pulse models` | Compare analyzed models |
| `/pulse useful` / `/pulse not-useful` | Rate the latest analysis (idempotent) |
| `/pulse yes` / `/pulse no` | Rate whether the session solved the problem |

The CLI supports `--file`, `--session`, and `--json`. `pulse analyze` is the versioned stdin/stdout JSON protocol used by adapters. `--deep` is reserved and explicitly **not implemented**; Pulse currently performs deterministic analysis only.

### `--unroll` mode

Score an unroll trace file (safe AST load, never executed):

```bash
uv run pulse --unroll ~/.hermes/traces/unrolled/<session>.py
uv run pulse --unroll ~/.hermes/traces/unrolled/<session>.py --json
```

Trace files carry TIMELINE steps but not full message text, so text-based
detectors degrade in this mode while timing/cost/graph signals are
authoritative. Three unroll-native detectors run on top of the standard set
(all thresholds **provisional** until ~100-session calibration):

- `latency_regression` (warning) — any step with `duration_ms > 5000`
- `cost_anomaly` (warning) — `cost_usd` above task ceiling (brainstorm $0.50, coding $5.00)
- `skill_deadweight` (warning with correction, else info) — skill in `ACTIVE_SKILLS` with zero `tool_call` steps

### Session gym

```bash
uv run python scripts/build_corpus.py --out corpus   # keep bottom-10 traces + sidecar JSON
```

A weekly cron (`pulse-session-gym-weekly`, Mondays 09:00) rescores the corpus
plus the week's new traces and reports worst session, total cost, and top
recurring signal.

```bash
uv run pulse replay --corpus corpus [--live] [--timeout 300] [--jobs 4] [--json]
```

Replays every `*.py` trace (dry-run from cache by default; `--live`
executes real LLM calls) with fan-out, per-trace timeout, and a
PASS/FAIL/TIMEOUT table. Exit 0 when all replay clean, 1 otherwise.
Model-change loop: replay → `build_corpus.py --traces corpus --out corpus`
(refresh mode rescues same-dir) → `pulse leaderboard` → `pulse_gate.py`.

### Leaderboard

```bash
uv run pulse leaderboard                    # ./corpus, no args needed
uv run pulse leaderboard --corpus DIR [--json]
```

Loads `*.score.json` sidecars (scores `*.py` traces live when a sidecar is
missing). Ranks top/bottom 3 per task type; session IDs are anonymized
(sha256, first 12 chars); score ties break toward lower cost.
Standalone: needs no Hermes install — just `pip install hermes-pulse` and a
directory of trace files.

### Quality as a merge check

```bash
uv run python scripts/pulse_gate.py --baseline corpus/main --candidate corpus/pr [--tolerance 5.0]
```

Exit 0 on pass, exit 1 on fail, with a per-task delta table. Fails when any
task-type mean score drops more than `--tolerance` points (default 5.0).
Standalone: needs no Hermes install — both inputs are plain directories of
trace files + sidecars. Copy-paste GitHub Actions snippet:

```yaml
- name: Pulse quality gate
  run: uv run python scripts/pulse_gate.py --baseline corpus/main --candidate corpus/pr
```

### Red-team calmness

Adversarial prompts live in `scripts/redteam/prompts.md` (12 prompts, 4
categories: ambiguous reference, contradictory instructions, mid-task scope
creep, missing-context traps). Run each prompt as a live session per model,
capture the traces, then rank:

```bash
uv run python scripts/redteam_score.py --traces redteam_traces/ [--json]
```

Per model: mean score plus frustration / correction-chain / reasoning-loop
counts per 10 sessions, calmest first. Standalone: needs no Hermes install
— input is a plain directory of trace files.

### Skill portability

```bash
uv run pulse portability                   # ./corpus, no args needed
uv run pulse portability --corpus DIR [--json]
```

Per skill: deadweight rate per model plus a verdict — `portable` (low
deadweight everywhere), `model_specific` (deadweight on some models, clean
on others), `dead` (deadweight everywhere). Reads `active_skills` +
`signals` straight from sidecars, so it never re-parses trace files;
corpora scored before v0.3 lack `active_skills` — rescore with
`scripts/build_corpus.py` to fill them in. Standalone: needs no Hermes
install.

## Native integrations

### Hermes Agent

The Hermes integration is a native `/pulse` plugin using Hermes's shared session store. It supports trend and model views across analyzed Hermes sessions.

### Pi

A native TypeScript extension lives in [`pi/`](pi/README.md). Run `pi -e ./pi/extensions/pulse.ts` from a checkout, or install the local package with `pi install ./pi`. It reads only Pi's public active-branch APIs, invokes the local `pulse analyze` protocol, and never parses Pi JSONL or Hermes SQLite. It provides the `/pulse` commands plus the optional `pulse_analyze` tool. Automatic analysis is opt-in via `PULSE_AUTO_ANALYZE=1` and runs after `agent_settled`.

Both integrations feed the same versioned normalized-message protocol and deterministic Python engine. Pi persists analysis and feedback as branch-local custom entries, so in-place branches do not leak results into sibling branches.

## Installation

From a checkout:

```bash
git clone https://github.com/dark5un/pulse.git ~/workspace/github.com/dark5un/pulse
cd ~/workspace/github.com/dark5un/pulse
PULSE_SOURCE_DIR="$PWD" bash install.sh
hermes plugins enable pulse
```

The installer places the native Hermes manifest and `__init__.py` under `${HERMES_HOME:-$HOME/.hermes}/plugins/pulse`. It can be rerun safely. `uninstall.sh` removes the plugin and learned weights but deliberately retains analysis data in `state.db`.

## Data and semantics

- Hermes state is profile-safe: `HERMES_HOME` selects `state.db`, `plugins/`, and `pulse_weights.json`; otherwise `$HOME/.hermes` is used.
- A session is analyzed only when it has **at least 5 total messages and at least 3 user turns**.
- Scores are clamped to 0–100. Attribution fields are normalized penalty shares: clean sessions return all zeroes, while non-clean sessions sum to 100%; system/other penalties contribute to `other_blame_pct`.
- Re-analysis updates analysis columns with an explicit SQLite upsert, preserving `feedback_rating` and `outcome_rating`.
- Repeating a feedback command reports that the result is already rated and does not add another learned-weight event. Rating changes are rejected to preserve event accounting.
- Pi feedback has independent usefulness (`useful`/`not-useful`) and outcome (`yes`/`no`) dimensions; repeats are idempotent and polarity changes are rejected. Automatic Pi analysis keys on the current ordered branch revision and retries failed invocations.
- The installer copies a self-contained plugin package, so loading works from an external working directory without repository `PYTHONPATH` or a resolved source symlink.
- Malformed session tool-call JSON is ignored safely. Explicit `tool_name` is preserved and used for runtime provenance.

## Development

```bash
uv sync --extra dev
uv run ruff check src/ tests/
uv run pyright src/pulse/ tests/
uv run pytest tests/ -q
```

Tests use an autouse temporary `HERMES_HOME`; they never write the developer's real Hermes state. The native plugin contract is `plugin.yaml` plus `__init__.py` exposing `register(ctx)`, as documented by Hermes Agent.

## Architecture

- `src/pulse/signals.py` — pure deterministic detectors
- `src/pulse/signals_unroll.py` — unroll-native detectors (latency, cost, skill deadweight; provisional thresholds)
- `src/pulse/unroll_loader.py` — safe trace loader (AST only, never executes) + timeline→messages
- `scripts/build_corpus.py` — session-gym corpus curator (bottom-10 + sidecar JSON)
- `src/pulse/task_type.py` — precedence-based classification
- `src/pulse/session_store.py` — shared defensive SQLite loader
- `src/pulse/weights.py` — validated atomic learned state
- `src/pulse/plugin.py` — slash command, persistence, and presentation

## License

MIT

Repository: https://github.com/dark5un/pulse

Every signal is a heuristic and should be treated as provisional.
