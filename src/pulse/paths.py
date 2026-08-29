"""Profile-safe paths for Hermes state."""
from __future__ import annotations

import os
from pathlib import Path


def hermes_home() -> Path:
    """Return the active Hermes home, honoring HERMES_HOME."""
    return Path(os.environ.get("HERMES_HOME", Path.home() / ".hermes")).expanduser()


def state_db(home: Path | None = None) -> Path:
    return (home or hermes_home()) / "state.db"


def weights_file(home: Path | None = None) -> Path:
    return (home or hermes_home()) / "pulse_weights.json"

# Backwards-compatible dynamic path proxy is intentionally avoided: callers should
# resolve paths at call time so changing profiles in a process is safe.
WEIGHTS_PATH = weights_file()
