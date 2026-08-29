# Pi Pulse follow-up work

The v1 adapter is implemented in `pi/` with the versioned Python protocol, branch normalization, bounded bridge, commands, custom-entry state, feedback idempotency, and opt-in settled-turn automation.

Remaining work:

- Add a dedicated TypeScript test runner and comprehensive unit tests for normalize/bridge/render/state/commands; the current environment has no local TypeScript compiler package.
- Exercise interactive Pi commands against a fixture session with a model-free harness or Pi SDK test helper.
- Improve attribution semantics and expose runtime logs/coaching detail consistently in the Pi card.
- Decide and document a release channel (Git tag vs npm), then add CI for the exact supported Pi version.
- Add explicit settings integration if Pi's stable settings API is selected; currently automation uses `PULSE_AUTO_ANALYZE=1`.
- Consider opt-in cross-session analytics separately; v1 intentionally remains branch/session-local for privacy.

Verification already performed: Python protocol probe through `uv run python -m pulse analyze`, full Python tests, Ruff, and Pyright. Before release, repeat isolated `pi install`/`pi -e` smoke tests with the installed Pi CLI and add the missing TypeScript test coverage.
