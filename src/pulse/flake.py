"""Flaky-agent divergence map (plan item 5 / C3).

``pulse flake --trace T --runs 5`` replays dry-run N times (dry-run first
catches harness nondeterminism — never ``--live`` here; live variance is a
separate question), diffs per-step (kind/name/text) signatures, and reports
per-step stability: 5/5 identical -> stable, else flaky with the diverging
step indices. Output feeds quarantine directly (mock step 7, constrain 12).
"""

from __future__ import annotations

import subprocess
import sys

from .unroll_loader import load_unroll_trace


def step_signature(entry: dict) -> str:
    """Stable identity of a step: kind + name/text, never timing."""
    kind = entry.get("kind", "?")
    payload = entry.get("name", "") or entry.get("text", "") or ""
    return f"{kind}:{payload}"


def _signatures(trace: str) -> list[str] | None:
    """Dry-run replay (validates it runs), then AST signatures. None on failure."""
    proc = subprocess.run(
        [sys.executable, trace], capture_output=True, text=True, timeout=300,
        check=False,
    )
    if proc.returncode != 0:
        return None
    try:
        bundle = load_unroll_trace(trace)
    except Exception:  # noqa: BLE001 — unloadable trace reads as failed
        return None
    return [step_signature(e) for e in bundle.timeline]


def flake(traces: list[str], timeout: int = 300) -> list[dict]:
    """Replay each trace dry-run; pairwise-compare signatures per step."""
    sig_runs: list[list[str] | None] = []
    for t in traces:
        try:
            proc = subprocess.run(
                [sys.executable, t], capture_output=True, text=True,
                timeout=timeout, check=False,
            )
            if proc.returncode != 0:
                sig_runs.append(None)
                continue
            sig_runs.append([step_signature(e) for e in load_unroll_trace(t).timeline])
        except Exception:  # noqa: BLE001 — timeout/unparseable reads as failed
            sig_runs.append(None)
    rows: list[dict] = []
    for trace, sigs in zip(traces, sig_runs, strict=True):
        if sigs is None:
            rows.append({
                "trace": trace, "stability": "0/0",
                "verdict": "replay-failed", "diverging_steps": [],
            })
            continue
        n = len(traces)
        match = sum(1 for other in sig_runs if other == sigs)
        diverging: list[int] = []
        for other in sig_runs:
            if other is not None and other != sigs:
                width = max(len(sigs), len(other))
                diverging.extend(
                    i for i in range(width)
                    if (sigs[i] if i < len(sigs) else None)
                    != (other[i] if i < len(other) else None)
                )
        diverging = sorted(set(diverging))
        rows.append({
            "trace": trace,
            "stability": f"{match}/{n}",
            "verdict": "stable" if match == n else "flaky",
            "diverging_steps": diverging,
        })
    return rows


def render(rows: list[dict]) -> str:
    if not rows:
        return "No traces replayed."
    lines = []
    for r in rows:
        name = r["trace"].rsplit("/", 1)[-1]
        div = f" diverging={r['diverging_steps']}" if r["diverging_steps"] else ""
        lines.append(f"{r['verdict']:<13} {r['stability']:>5}  {name}{div}")
    return "\n".join(lines)


__all__ = ["flake", "render", "step_signature"]
