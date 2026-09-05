"""Experiment manifests (plan item 4 / B3): paper-grade run discipline.

``pulse experiment`` writes manifest + results dir: seed, model version pin,
timestamp, exact trace hashes — so a reviewer can rerun.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path


def _pulse_version() -> str:
    try:
        return version("hermes-pulse")
    except Exception:  # noqa: BLE001 — dev checkout without install
        return "dev"


def write_manifest(out_dir: str | Path, traces: list[str], variable: str) -> dict:
    """Write manifest.json pinning variable, versions, trace hashes."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    entries = []
    for t in traces:
        p = Path(t)
        entries.append(
            {
                "path": p.name,
                "sha256": hashlib.sha256(p.read_bytes()).hexdigest(),
            }
        )
    manifest = {
        "variable": variable,
        "timestamp": datetime.now(UTC).isoformat(),
        "pulse_version": _pulse_version(),
        "traces": entries,
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2))
    return manifest


__all__ = ["write_manifest"]
