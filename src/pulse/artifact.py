"""Reproducibility artifacts (plan item 4 / B4): bundle + verify.

``pulse bundle <trace.py>`` emits ``<session>.artifact/`` (trace, sidecar,
run-manifest with tool versions and hashes, redaction receipt).
``pulse verify <artifact/>`` inspects the artifact structurally and checks
the score reproduces exactly.

Trust boundary: ``verify`` inspects — it never executes. Trace files are
generated Python programs, so executing one during verification would be
arbitrary host code execution on whoever verifies a downloaded artifact.
Replay belongs to the explicit ``pulse replay`` path, which the operator
opts into per trace.
"""

from __future__ import annotations

import hashlib
import json
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

import pulse
from pulse.export import REDACTION_RECEIPT
from pulse.trace_score import score_trace_file

#: Bump whenever the artifact on-disk schema changes in a way old
#: verifiers cannot read. Stored in ``run-manifest.json``.
ARTIFACT_SCHEMA = 2

#: Constants a trace must define for structural verification. Mirrors the
#: loader's core keys (a verifiable trace is a parseable, scorable trace).
REQUIRED_TRACE_CONSTANTS = ("SESSION_ID", "MODEL", "TIMELINE")


def _pulse_version() -> str:
    try:
        return version("hermes-pulse")
    except PackageNotFoundError:
        # Editable checkout, isolated tool install, or any environment
        # without distribution metadata — fall back to the single source
        # of truth in the package itself so run-manifests stay pinnable.
        return pulse.__version__


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
        "artifact_schema": ARTIFACT_SCHEMA,
        "trace": src.name,
        "sha256": hashlib.sha256(src.read_bytes()).hexdigest(),
        "sidecar": sidecar_note,
        "pulse_version": _pulse_version(),
        "redaction_receipt": REDACTION_RECEIPT,
    }
    (dest / "run-manifest.json").write_text(json.dumps(manifest, indent=2))
    return str(dest)


def verify(artifact_dir: str | Path) -> dict:
    """Inspect an artifact without executing it.

    Returns ``{"loads", "hash_matches", "score_reproduces", "detail"}``:

    - ``loads``: the trace parses and defines the required constants.
    - ``hash_matches``: current trace bytes match the ``run-manifest.json``
      sha256 pinned at bundle time (tamper evidence).
    - ``score_reproduces``: ``score_trace_file()`` on the trace equals the
      pinned sidecar score (or True when no sidecar was bundled).
    """
    d = Path(artifact_dir)
    traces = sorted(d.glob("*.py"))
    if not traces:
        return {
            "loads": False,
            "hash_matches": False,
            "score_reproduces": False,
            "detail": "no trace found",
        }
    trace = traces[0]
    manifest: dict = {}
    manifest_path = d / "run-manifest.json"
    if manifest_path.exists():
        try:
            manifest = json.loads(manifest_path.read_text())
        except (json.JSONDecodeError, OSError) as e:
            return {
                "loads": False,
                "hash_matches": False,
                "score_reproduces": False,
                "detail": f"run-manifest unreadable: {e}",
            }
    required = ", ".join(REQUIRED_TRACE_CONSTANTS)
    try:
        from pulse.unroll_loader import load_unroll_trace

        load_unroll_trace(str(trace))
        text = trace.read_text()
        missing = [
            const
            for const in REQUIRED_TRACE_CONSTANTS
            if f"{const} =" not in text and f"{const}=" not in text
        ]
        if missing:
            return {
                "loads": False,
                "hash_matches": False,
                "score_reproduces": False,
                "detail": f"missing required trace constants: {', '.join(missing)} (need {required})",
            }
    except ValueError as e:
        return {
            "loads": False,
            "hash_matches": False,
            "score_reproduces": False,
            "detail": f"trace does not parse: {e}",
        }
    except OSError as e:
        return {
            "loads": False,
            "hash_matches": False,
            "score_reproduces": False,
            "detail": f"trace unreadable: {e}",
        }
    digest = hashlib.sha256(trace.read_bytes()).hexdigest()
    pinned = manifest.get("sha256")
    if pinned is None:
        return {
            "loads": True,
            "hash_matches": False,
            "score_reproduces": False,
            "detail": "run-manifest has no sha256 to compare against",
        }
    if digest != pinned:
        short = digest[:12]
        return {
            "loads": True,
            "hash_matches": False,
            "score_reproduces": False,
            "detail": f"hash MISMATCH: trace sha256 {short}… != manifest {str(pinned)[:12]}… (tampered after bundling?)",
        }
    try:
        rec = score_trace_file(trace)
        sidecars = sorted(d.glob("*.score.json"))
        if sidecars:
            pinned_score = json.loads(sidecars[0].read_text())
            reproduces = (
                rec["score"] == pinned_score.get("score")
                and rec["penalty"] == pinned_score.get("penalty")
            )
            detail = f"hash matches, score={rec['score']} pinned={pinned_score.get('score')}"
        else:
            reproduces = True
            detail = f"hash matches, score={rec['score']} (no pinned sidecar)"
    except Exception as e:  # noqa: BLE001 — report, don't crash
        return {
            "loads": True,
            "hash_matches": True,
            "score_reproduces": False,
            "detail": f"hash matches, rescore failed: {e}",
        }
    return {
        "loads": True,
        "hash_matches": True,
        "score_reproduces": reproduces,
        "detail": detail,
    }


__all__ = [
    "ARTIFACT_SCHEMA",
    "REQUIRED_TRACE_CONSTANTS",
    "bundle",
    "verify",
]
