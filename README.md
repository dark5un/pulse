# Pulse — Session Health Monitor for AI Conversations

![Pulse hero](assets/pulse-hero.png)

Analyze your Hermes Agent conversations with evidence-based signals that attribute session quality to the human, the agent, or systemic issues. Tracks trends across sessions, compares model performance, and learns from your feedback.

## What it does

Every `/pulse` run produces a card with:

- **Session summary** — turns, tokens, tool calls, model used
- **Signals** — what went well or poorly, attributed to you or the agent
- **Coaching tips** — actionable suggestions based on detected patterns
- **Feedback loop** — tell Pulse when it's right or wrong, and it adjusts

## Subcommands

| Command | What it does |
|---|---|
| `/pulse` | Analyze the current session |
| `/pulse trends` | Last 20 sessions, per-model breakdown |
| `/pulse models` | Compare performance across all models |
| `/pulse useful` | Mark last analysis as accurate |
| `/pulse not-useful` | Mark last analysis as inaccurate |
| `/pulse yes` / `/pulse no` | Report whether the session solved your problem |

## Installation

### 1. Install the pulse project

```bash
git clone git@github.com:dark5un/pulse.git ~/workspace/pulse
cd ~/workspace/pulse
uv sync --extra dev
```

### 2. Install the Hermes plugin

```bash
mkdir -p ~/.hermes/plugins/pulse
cp ~/workspace/pulse/src/pulse/plugin.yaml ~/.hermes/plugins/pulse/
ln -s ~/workspace/pulse/src/pulse/plugin.py ~/.hermes/plugins/pulse/__init__.py
```

### 3. Enable the plugin

```bash
hermes plugins enable pulse
```

Then restart Hermes (`/exit` then `hermes`).

## Development

```bash
cd ~/workspace/pulse
uv run pytest tests/ -q      # 45 tests
ruff check src/ tests/        # Lint
pyright src/pulse/ tests/     # Type check
```

## Signals

| Signal | Detects | Attributable to |
|---|---|---|
| `correction_chain` | 3+ consecutive corrections | user |
| `frustration` | Frustration keywords across turns | user |
| `goal_drift` | Multiple direction changes | user |
| `vague_prompts` | Low-specificity prompts | user |
| `shrinking_prompts` | Prompts getting much shorter | user |
| `reasoning_loop` | Agent self-correcting in place | agent |
| `premature_stop` | Agent asking to stop mid-task | agent |
| `tool_repetition` | Same tool called repeatedly | agent |
| `tool_error` | Explicit tool failures | agent |
| `shallow_read` | Low Read:Edit ratio | agent |
| `low_diversity` | Narrow tool repertoire | agent |

## Architecture

- **Signals**: deterministic heuristics in `src/pulse/signals.py` (11 detectors)
- **Weights**: Bayesian feedback loop in `src/pulse/weights.py`
- **Plugin**: Hermes slash command in `src/pulse/plugin.py`
- **Storage**: `pulse_results` table in Hermes `state.db`

## License

MIT