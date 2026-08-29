# Pi Pulse extension

Native Pi adapter for the harness-neutral Pulse session-quality engine. It uses Pi's public `SessionManager.getBranch()` and `appendEntry()` APIs; it never reads Pi JSONL or Hermes SQLite files.

## Local use

From the repository root:

```bash
pi -e ./pi/extensions/pulse.ts
```

For a project package, add the checkout path with `pi install ./pi`. The release channel is npm (`@dark5un/pi-pulse`); Git tags remain a source-install fallback. Pulse must be available as `pulse` on `PATH`; set `PULSE_EXECUTABLE=/absolute/path/to/pulse` to override. The bridge sends one versioned JSON document on stdin and expects exactly one JSON result on stdout.

Commands: `/pulse`, `/pulse trends`, `/pulse models`, `/pulse useful`, `/pulse not-useful`, `/pulse yes`, `/pulse no`. The optional `pulse_analyze` tool lets the agent request a structured report; it never records feedback automatically.

Automatic analysis is disabled by default. Opt in with `PULSE_AUTO_ANALYZE=1`; it runs quietly after `agent_settled`, once per unchanged ordered branch revision, and retries after failures. Analyses receive unique IDs and feedback is idempotent per analysis and per dimension: usefulness (`useful`/`not-useful`) and outcome (`yes`/`no`) can each be rated once, while polarity changes are rejected. Analyses and feedback are minimal, branch-local custom session entries (`pulse:analysis` and `pulse:feedback`), not a global database. The extension has full process permissions, so review source before loading it.

Requirements: Pi 0.84.x, Node.js, and a working Pulse executable. The package peer dependency deliberately bounds support to `>=0.84.0 <0.85.0`; CI exercises Pi 0.84.4. Headless/print/RPC modes receive deterministic text or avoid UI calls. In-memory/ephemeral Pi sessions still analyze; persistence is unavailable when Pi itself is not persisted.

Development: from `pi/`, run `npm ci`, `npm run check`, and `npm test`, plus the repository Python checks. `npm ci` installs the local TypeScript/Vitest development dependencies. `PULSE_AUTO_ANALYZE=1` is the explicit v1 settings integration; Pi settings integration is intentionally not implicit.

License: MIT.

## Security and troubleshooting

The bridge uses `child_process.spawn` with an argument array (no shell), bounds output, captures diagnostics separately, and applies a timeout. A missing executable produces a notification rather than crashing Pi. Reload the extension with `/reload` after changing source. Project-local packages may require Pi project trust.
