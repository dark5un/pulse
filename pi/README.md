# Pi Pulse extension

Native Pi adapter for the deterministic Python Pulse engine. It uses Pi's public `SessionManager.getBranch()` and `appendEntry()` APIs; it never reads Pi JSONL or Hermes SQLite files.

## Local use

From the repository root:

```bash
pi -e ./pi/extensions/pulse.ts
```

For a project package, add the checkout path with `pi install ./pi`, or install a future Git/npm release. Pulse must be available as `pulse` on `PATH`; set `PULSE_EXECUTABLE=/absolute/path/to/pulse` to override. The bridge sends one versioned JSON document on stdin and expects exactly one JSON result on stdout.

Commands: `/pulse`, `/pulse trends`, `/pulse models`, `/pulse useful`, `/pulse not-useful`, `/pulse yes`, `/pulse no`.

Automatic analysis is disabled by default. Opt in with `PULSE_AUTO_ANALYZE=1`; it runs quietly after `agent_settled`, once per active branch leaf. Analyses and feedback are minimal, branch-local custom session entries (`pulse:analysis` and `pulse:feedback`), not a global database. The extension has full process permissions, so review source before loading it.

Requirements: Pi 0.84.x or later, Node.js, and a working Pulse executable. Headless/print/RPC modes receive deterministic text or avoid UI calls. In-memory/ephemeral Pi sessions still analyze; persistence is unavailable when Pi itself is not persisted.

Development: from `pi/`, run `npm run check` and `npm test`, plus the repository Python checks. `npm install` installs the local TypeScript/Vitest development dependencies.

License: MIT.

## Security and troubleshooting

The bridge uses `child_process.spawn` with an argument array (no shell), bounds output, captures diagnostics separately, and applies a timeout. A missing executable produces a notification rather than crashing Pi. Reload the extension with `/reload` after changing source. Project-local packages may require Pi project trust.
