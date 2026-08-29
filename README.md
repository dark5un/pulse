# Pulse — Session Health Monitor for AI Conversations

Pulse is a deterministic Hermes Agent plugin that analyzes conversations with evidence-based signals attributed to the user, agent, or system. It stores one replaceable analysis snapshot per session while preserving feedback and outcome ratings.

## Commands

| Command | Description |
|---|---|
| `/pulse` | Analyze the current/latest session |
| `/pulse trends` | Show the latest 20 analyses |
| `/pulse models` | Compare analyzed models |
| `/pulse useful` / `/pulse not-useful` | Rate the latest analysis (idempotent) |
| `/pulse yes` / `/pulse no` | Rate whether the session solved the problem |

The CLI supports `--file`, `--session`, and `--json`. `pulse analyze` is the versioned stdin/stdout JSON protocol used by adapters. `--deep` is reserved and explicitly **not implemented**; Pulse currently performs deterministic analysis only.

## Pi integration

A native Pi extension lives in [`pi/`](pi/README.md). Run `pi -e ./pi/extensions/pulse.ts` from a checkout, or install the local package with `pi install ./pi`. It uses Pi's public active-branch APIs and invokes the local `pulse analyze` protocol; it does not parse Pi JSONL or Hermes SQLite. Automatic analysis is opt-in via `PULSE_AUTO_ANALYZE=1` and the bridge executable can be set with `PULSE_EXECUTABLE`.

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
- Scores are clamped to 0–100. User, agent, and system/other penalties are calculated separately; system/other penalties contribute to `other_blame_pct`.
- Re-analysis updates analysis columns with an explicit SQLite upsert, preserving `feedback_rating` and `outcome_rating`.
- Repeating a feedback command reports that the result is already rated and does not add another learned-weight event. Rating changes are rejected to preserve event accounting.
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
- `src/pulse/task_type.py` — precedence-based classification
- `src/pulse/session_store.py` — shared defensive SQLite loader
- `src/pulse/weights.py` — validated atomic learned state
- `src/pulse/plugin.py` — slash command, persistence, and presentation

## License

MIT

Repository: https://github.com/dark5un/pulse

Every signal is a heuristic and should be treated as provisional.
