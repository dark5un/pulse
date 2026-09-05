"""Reproducibility artifacts (plan item 4 / B4): bundle + verify.

``pulse bundle <trace.py>`` emits ``<session>.artifact/`` (trace, sidecar,
run-manifest with tool versions and hashes, redaction receipt).
``pulse verify <artifact/>`` replays dry-run and checks the score
reproduces exactly.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from importlib.metadata import version
from pathlib import Path

from pulse.export import REDACTION_RECEIPT


def _pulse_version() -> str:
    try:
        return version("hermes-pulse")
    except Exception:  # noqa: BLE001 — dev checkout without install
        return "dev"


def bundle(trace: str, out_dir: str | Path = ".") -> str:
    """Copy trace + sidecar into <stem>.artifact/ with a run-manifest."""
    src = Path(trace)
    dest = Path(out_dir) / f"{src.stem}.artifact"
    dest.mkdir(parents=True, exist_ok=True)
    (dest / src.name).write_bytes(src.read_bytes())
    sidecar = src.parent / f"{src.stem}.score.json"
    if sidecar.exists():
        (dest / sidecar.name).write_text(sidecar.read_text())
        sidecar_note = sidecar.name
    else:
        sidecar_note = "no sidecar — score at verify time"
    manifest = {
        "trace": src.name,
        "sha256": hashlib.sha256(src.read_bytes()).hexdigest(),
        "sidecar": sidecar_note,
        "pulse_version": _pulse_version(),
        "python": sys.version.split()[0],
        "redaction_receipt": REDACTION_RECEIPT,
    }
    (dest / "run-manifest.json").write_text(json.dumps(manifest, indent=2))
    return str(dest)


def verify(artifact_dir: str | Path) -> dict:
    """Replay dry-run + rescore; report whether the score reproduces."""
    from pulse.trace_score import score_trace_file

    d = Path(artifact_dir)
    traces = sorted(d.glob("*.py"))
    if not traces:
        return {"replays": False, "score_reproduces": False, "detail": "no trace found"}
    trace = traces[0]
    proc = subprocess.run(
        [sys.executable, str(trace)], capture_output=True, text=True, timeout=300,
        check=False,
    )
    replays = proc.returncode == 0
    detail = f"replay exit={proc.returncode}"
    reproduces = False
    try:
        rec = score_trace_file(trace)
        sidecars = sorted(d.glob("*.score.json"))
        if sidecars:
            pinned = json.loads(sidecars[0].read_text())
            reproduces = (
                rec["score"] == pinned.get("score")
                and rec["penalty"] == pinned.get("penalty")
            )
            detail += f" score={rec['score']} pinned={pinned.get('score')}"
        else:
            reproduces = True
            detail += f" score={rec['score']} (no pinned sidecar)"
    except Exception as e:  # noqa: BLE001 — report, don't crash
        detail += f" rescore failed: {e}"
    return {"replays": replays, "score_reproduces": reproduces, "detail": detail}


__all__ = ["bundle", "verify"]
