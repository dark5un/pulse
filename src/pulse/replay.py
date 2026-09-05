"""Replay runner for pulse-gym corpora (plan item 1 / A1).

Runs each ``*.py`` trace in a subprocess (same interpreter — has deps),
sequentially or fanned out with threads. Dry-run by default; ``--live``
passes ``--live`` through to the trace replayer. Per-trace timeout;
result rows carry trace path, ok flag, returncode, timeout flag, output tail.
"""

from __future__ import annotations

import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor

OUTPUT_TAIL_CHARS = 4000


def replay_one(trace: str, live: bool = False, timeout: int = 300) -> dict:
    """Replay a single trace file. Returns a result row dict."""
    cmd = [sys.executable, trace] + (["--live"] if live else [])
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=False)
        output = (proc.stdout or "") + (proc.stderr or "")
        return {
            "trace": trace,
            "ok": proc.returncode == 0,
            "returncode": proc.returncode,
            "timed_out": False,
            "output": output[-OUTPUT_TAIL_CHARS:],
        }
    except subprocess.TimeoutExpired as e:
        partial = (e.stdout or b"") if isinstance(e.stdout, bytes) else (e.stdout or "")
        if isinstance(partial, bytes):
            partial = partial.decode(errors="replace")
        return {
            "trace": trace,
            "ok": False,
            "returncode": -1,
            "timed_out": True,
            "output": str(partial)[-OUTPUT_TAIL_CHARS:],
        }


def replay_corpus(
    traces: list[str], live: bool = False, timeout: int = 300, jobs: int = 4
) -> list[dict]:
    """Replay every trace; fan out with threads when jobs > 1."""
    if not traces:
        return []
    if jobs <= 1 or len(traces) == 1:
        return [replay_one(t, live=live, timeout=timeout) for t in traces]
    with ThreadPoolExecutor(max_workers=jobs) as pool:
        return list(pool.map(lambda t: replay_one(t, live=live, timeout=timeout), traces))


__all__ = ["OUTPUT_TAIL_CHARS", "replay_corpus", "replay_one"]
