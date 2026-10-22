"""Pulse-owned redacted snapshot corpus (deep-judge gate plan M2 + M3).

``pulse corpus export`` reads the Hermes session DB **read-only** and writes
one JSON snapshot per eligible session. The filename is the first 16 hex of
``sha256(canonical snapshot bytes)`` — content-addressed, so an unchanged
session is skipped on re-export and a revisited session (hash changed) is
re-exported while its superseded snapshot is marked in the index.

Schema is Pulse's own (never a host format): message skeleton
(role / redacted content / tool-name), model, timestamps, task_type, and an
ADVISORY deterministic-label sidecar (the kappa input is always recomputed
via ``extract_signals`` at gate run time — detector thresholds can drift
between export and run, so the sidecar only exists for selection). Text is
redacted AT WRITE TIME with the same ``redact_text()`` as the prompt
boundary; each snapshot stamps ``redact_version`` and ``approx_truncated``
(transcript exceeds the ``build_prompt`` budget — computable at export).

The export skip predicate is ``extract_signals``' own session-too-short
guard, so the corpus can never inject trivially all-negative rows.

Corpus files are never git-tracked: ``.gitignore`` ships ``corpus/``. Only
selection manifests (hashes + metadata, no transcripts) get committed.
Membership is run-frozen: a re-pin is a NEW manifest, never an edit.
"""

from __future__ import annotations

import hashlib
import json
import random
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path
from typing import Any

from . import session_store
from .paths import state_db
from .session_store import SchemaIncompatibleError
from .signals import extract_signals
from .signals_deep import (
    PROMPT_VERSION,
    REDACT_VERSION,
    TRUNCATION_MARKER,
    build_prompt,
    redact_text,
)

SNAPSHOT_SCHEMA = "pulse-corpus-snapshot/v1"
INDEX_SCHEMA = "pulse-corpus-index/v1"
MANIFEST_SCHEMA = "pulse-corpus-manifest/v1"

#: The comparable kappa pairs (agreement_cli semantics): selection floors
#: are enforced per pair across the selected corpus.
COMPARABLE_PAIRS = ("correction_chain", "premature_stop")


class CorpusError(RuntimeError):
    """Loud corpus-layer failure (missing index, missing snapshots, floors)."""


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _pulse_version() -> str:
    try:
        return version("hermes-pulse")
    except Exception:  # noqa: BLE001 — dev checkout without install
        return "dev"


def _canonical_bytes(payload: dict[str, Any]) -> bytes:
    return (json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode(
        "utf-8"
    )


# ── Export (M2) ────────────────────────────────────────────────────────────


@dataclass
class ExportSummary:
    seen: int = 0
    skipped_short: int = 0
    skipped_unchanged: int = 0
    exported_new: int = 0
    re_exported: int = 0
    superseded: int = 0
    db_path: str = ""
    corpus_dir: str = ""

    def line(self) -> str:
        return (
            f"seen={self.seen} skipped_short={self.skipped_short} "
            f"unchanged={self.skipped_unchanged} exported_new={self.exported_new} "
            f"re_exported={self.re_exported} superseded={self.superseded}"
        )


def approx_truncated(messages: list[dict]) -> bool:
    """True when build_prompt() would disclose a middle cut for this
    transcript. ADVISORY at the default (fallback) budget: the actual
    per-call truncation is model-derived and recorded at judge time
    (ADR 0010) — this stamp only pre-screens at export."""
    return TRUNCATION_MARKER in build_prompt(messages)


def snapshot_payload(session: dict[str, Any], messages: list[dict]) -> dict[str, Any] | None:
    """Build one snapshot payload, or None when the session is ineligible.

    Ineligibility uses the EXACT same predicate as ``extract_signals``
    (session-too-short guard), and the advisory deterministic labels come
    from that same call — predicate and labels cannot drift by construction.
    """
    result = extract_signals(messages)
    if result.skipped_reason:
        return None
    skeleton: list[dict[str, str]] = []
    for msg in messages:
        entry: dict[str, str] = {
            "role": str(msg.get("role", "?")),
            "content": redact_text(str(msg.get("content", ""))),
        }
        tool_name = msg.get("tool_name")
        if tool_name:
            entry["tool_name"] = str(tool_name)
        skeleton.append(entry)
    signal_names = sorted({s.name for s in result.signals})
    payload: dict[str, Any] = {
        "schema": SNAPSHOT_SCHEMA,
        "session_id": session["id"],
        "model": session.get("model") or "unknown",
        "started_at": session.get("started_at"),
        "ended_at": session.get("ended_at"),
        "task_type": result.metrics.get("task_type", ""),
        "message_count": len(messages),
        "messages": skeleton,
        "redact_version": REDACT_VERSION,
        "approx_truncated": approx_truncated(messages),
        "advisory": {
            "note": "advisory only — kappa input is recomputed via extract_signals at run time (ML-B7)",
            "pulse_version": _pulse_version(),
            "det_signals": signal_names,
            "det_pairs": {p: 1 if p in signal_names else 0 for p in COMPARABLE_PAIRS},
        },
    }
    return payload


def read_index(corpus_dir: Path) -> dict[str, Any]:
    path = corpus_dir / "index.json"
    if not path.exists():
        raise CorpusError(
            f"no corpus index at {path} — run `pulse corpus export --out {corpus_dir}` first"
        )
    try:
        index = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        raise CorpusError(f"corpus index unreadable: {path}: {e}") from e
    if index.get("schema") != INDEX_SCHEMA:
        raise CorpusError(f"corpus index schema mismatch: {path}")
    return index


def write_index(corpus_dir: Path, entries: dict[str, dict[str, Any]]) -> None:
    index = {
        "schema": INDEX_SCHEMA,
        "written_at": _utc_now_iso(),
        "pulse_version": _pulse_version(),
        "redact_version": REDACT_VERSION,
        "entries": entries,
    }
    (corpus_dir / "index.json").write_text(
        json.dumps(index, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8"
    )


def export_corpus(
    out_dir: str | Path, db_path: str | Path | None = None, limit: int = 0
) -> ExportSummary:
    """Hash-incremental snapshot export from the session DB (read-only).

    ``limit`` > 0 restricts to the most recent N sessions (dry-run aid).
    Missing/locked DB raises SchemaIncompatibleError naming the resolved
    path (M0 export-half contract). The index sidecar maps
    hash -> (session_id, model, task_type, exported_at) for human review
    via ``pulse corpus list``.
    """
    db = Path(db_path) if db_path else state_db()
    corpus_dir = Path(out_dir)
    corpus_dir.mkdir(parents=True, exist_ok=True)
    summaries = session_store.list_sessions(db)
    if limit > 0:
        summaries = summaries[-limit:]
    try:
        index = read_index(corpus_dir)
        entries: dict[str, dict[str, Any]] = dict(index["entries"])
    except CorpusError:
        entries = {}
    summary = ExportSummary(db_path=str(db), corpus_dir=str(corpus_dir))
    for brief in summaries:
        summary.seen += 1
        messages, _sid, model = session_store.load_session(brief["id"], db)
        session = {**brief, "model": brief.get("model") or model}
        payload = snapshot_payload(session, messages)
        if payload is None:  # same skip predicate as extract_signals
            summary.skipped_short += 1
            continue
        content = _canonical_bytes(payload)
        digest = hashlib.sha256(content).hexdigest()
        name = f"{digest[:16]}.json"
        path = corpus_dir / name
        if path.exists():
            summary.skipped_unchanged += 1
            if name not in entries:
                entries[name] = _index_entry(payload, digest)
            continue
        # Supersede older active snapshots for the same session id: a
        # revisited session re-exports, the old hash version is marked.
        replaced = 0
        for old in entries.values():
            if old.get("session_id") == payload["session_id"] and not old.get("superseded_by"):
                old["superseded_by"] = name
                replaced += 1
        summary.superseded += replaced
        if replaced:
            summary.re_exported += 1
        else:
            summary.exported_new += 1
        path.write_bytes(content)
        entries[name] = _index_entry(payload, digest)
    write_index(corpus_dir, entries)
    return summary


def _index_entry(payload: dict[str, Any], digest: str) -> dict[str, Any]:
    return {
        "sha256": digest,
        "session_id": payload["session_id"],
        "model": payload["model"],
        "task_type": payload["task_type"],
        "message_count": payload["message_count"],
        "approx_truncated": payload["approx_truncated"],
        "redact_version": payload["redact_version"],
        "pulse_version": payload["advisory"]["pulse_version"],
        "exported_at": _utc_now_iso(),
    }


# ── Selection + manifest (M3) ─────────────────────────────────────────────


@dataclass
class SelectionCounts:
    eligible: int = 0
    core: int = 0
    enriched: int = 0
    deduped: int = 0
    det_positive: dict[str, dict[str, int]] = field(
        default_factory=lambda: {
            p: {"core": 0, "enriched": 0, "total": 0} for p in COMPARABLE_PAIRS
        }
    )


class SelectionError(CorpusError):
    def __init__(self, message: str, counts: SelectionCounts) -> None:
        super().__init__(message)
        self.counts = counts


def load_active_snapshots(corpus_dir: Path) -> tuple[list[dict[str, Any]], int]:
    """Return (active snapshot records, deduped_superseded_count).

    Dedupe rule: one active snapshot per session id — newest export wins;
    a revisited session's two hash-versions can never both occupy n>=50
    slots or pair with each other. Each record carries the file's full
    sha256 (verified against content) plus the advisory det-pair labels.
    """
    index = read_index(corpus_dir)
    raw_entries = index["entries"]
    # Newest exported_at wins per session id (tie -> name order for
    # determinism); earlier versions count as deduped-away.
    by_session: dict[str, tuple[str, dict[str, Any]]] = {}
    deduped = 0
    for name, entry in sorted(raw_entries.items(), key=lambda kv: (kv[1].get("exported_at", ""), kv[0])):
        sid = entry["session_id"]
        if entry.get("superseded_by"):
            continue
        if sid in by_session:
            deduped += 1
        by_session[sid] = (name, entry)
    records: list[dict[str, Any]] = []
    missing: list[str] = []
    for sid, (name, entry) in sorted(by_session.items()):
        path = corpus_dir / name
        if not path.exists():
            missing.append(name)
            continue
        payload = json.loads(path.read_text(encoding="utf-8"))
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        if actual != entry["sha256"] or payload.get("schema") != SNAPSHOT_SCHEMA:
            raise CorpusError(
                f"corpus integrity failure: {path} content hash != index sha256 "
                "(or schema mismatch) — re-run `pulse corpus export`"
            )
        records.append(
            {
                "path": name,
                "sha256": actual,
                "session_id": sid,
                "model": payload.get("model", ""),
                "task_type": payload.get("task_type", ""),
                "approx_truncated": bool(payload.get("approx_truncated", False)),
                "redact_version": payload.get("redact_version", ""),
                "det_pairs": payload.get("advisory", {}).get("det_pairs", {}),
            }
        )
    if missing:
        raise CorpusError(
            f"{len(missing)} of {len(by_session)} indexed snapshots missing from {corpus_dir} "
            f"(corpus is not git-tracked): {', '.join(missing[:5])} — re-run pulse corpus export"
        )
    return records, deduped


def select_corpus(
    corpus_dir: str | Path,
    n_core: int = 50,
    n_enriched: int = 50,
    pair_floor: int = 10,
    seed: int = 20261022,
    out_path: str | Path | None = None,
    judge: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Stratified selection (M3): random core + signal-enriched half.

    - core: uniform random over all eligible snapshots (generalization read)
    - enriched: drawn from the detector-positive pool with a per-pair
      floor (>= pair_floor detector-positive per comparable pair) so no
      kappa cell can hit the base-rate collapse again
    - dedupe by session id (newest snapshot wins) before selecting
    - seeded (random.Random(seed)); the manifest records seed, corpus
      hashes, redact_version, PROMPT_VERSION, model/base_url placeholders
      (judge identity finalized at run time), and stratum per item.

    Raises SelectionError (nothing written) when eligibility counts or the
    per-pair detector-positive floors cannot be met — bars are never
    silently relaxed. Judge-positive floors are NOT computable in the
    corpus layer (no judge calls); they are re-checked at agreement time.
    """
    import os

    d = Path(corpus_dir)
    records, deduped = load_active_snapshots(d)
    counts = SelectionCounts(eligible=len(records), deduped=deduped)
    if counts.eligible < n_core + n_enriched:
        raise SelectionError(
            f"corpus too small: {counts.eligible} eligible snapshots < n_core+n_enriched="
            f"{n_core + n_enriched}; export more sessions (do not relax bars)",
            counts,
        )
    rng = random.Random(seed)
    pools = {p: [r for r in records if r["det_pairs"].get(p)] for p in COMPARABLE_PAIRS}
    chosen: list[tuple[str, dict[str, Any]]] = []
    taken: set[str] = set()
    # Enriched stratum first: guarantee per-pair floors, then fill.
    for pair in COMPARABLE_PAIRS:
        avail = [r for r in pools[pair] if r["session_id"] not in taken]
        if len(avail) < pair_floor:
            raise SelectionError(
                f"detector-positive floor unmet for pair {pair!r}: pool {len(avail)} < floor "
                f"{pair_floor}; corpus cannot support this gate (escalate, do not relax)",
                counts,
            )
        pick = rng.sample(sorted(avail, key=lambda r: r["sha256"]), pair_floor)
        for r in pick:
            chosen.append(("enriched", r))
            taken.add(r["session_id"])
    if len(chosen) > n_enriched:
        raise SelectionError(
            f"configuration infeasible: {len(COMPARABLE_PAIRS)} pair floors x {pair_floor} = "
            f"{len(chosen)} floor picks exceed n_enriched {n_enriched}",
            counts,
        )
    enrich_pool = [r for r in records if r["session_id"] not in taken and any(
        r["det_pairs"].get(p) for p in COMPARABLE_PAIRS
    )]
    need_enrich = n_enriched - len(chosen)
    if len(enrich_pool) < need_enrich:
        raise SelectionError(
            f"enriched stratum shortfall: {len(chosen)} floor picks + pool {len(enrich_pool)} "
            f"< n_enriched {n_enriched}",
            counts,
        )
    for r in rng.sample(sorted(enrich_pool, key=lambda r: r["sha256"]), need_enrich):
        chosen.append(("enriched", r))
        taken.add(r["session_id"])
    core_pool = [r for r in records if r["session_id"] not in taken]
    if len(core_pool) < n_core:
        raise SelectionError(
            f"core stratum shortfall: remaining pool {len(core_pool)} < n_core {n_core}",
            counts,
        )
    for r in rng.sample(sorted(core_pool, key=lambda r: r["sha256"]), n_core):
        chosen.append(("core", r))
        taken.add(r["session_id"])
    # Per-pair, per-stratum detector-positive counts (selection-time,
    # advisory labels; the gate recomputes at run time).
    for stratum, rec in chosen:
        for pair in COMPARABLE_PAIRS:
            if rec["det_pairs"].get(pair):
                counts.det_positive[pair][stratum] += 1
                counts.det_positive[pair]["total"] += 1
    counts.core = sum(1 for s, _ in chosen if s == "core")
    counts.enriched = sum(1 for s, _ in chosen if s == "enriched")
    items = [
        {
            "path": rec["path"],
            "sha256": rec["sha256"],
            "session_id": rec["session_id"],
            "stratum": stratum,
            "task_type": rec["task_type"],
            "model": rec["model"],
            "approx_truncated": rec["approx_truncated"],
            "det_pairs": {p: int(rec["det_pairs"].get(p, 0)) for p in COMPARABLE_PAIRS},
        }
        for stratum, rec in sorted(chosen, key=lambda t: (t[0], t[1]["sha256"]))
    ]
    judge_identity = judge or {
        "lane": "api",
        "model": os.environ.get("PULSE_JUDGE_MODEL", ""),
        "base_url": os.environ.get("PULSE_JUDGE_BASE_URL", ""),
        "model_checkpoint": None,
        "note": (
            "judge identity placeholder fields per plan M3 — finalized and verified "
            "against the live endpoint at gate run time (S1 makes no judge calls); "
            "judge-positive floors (>=10 provisional, ML-B1) are re-checked then."
        ),
    }
    manifest: dict[str, Any] = {
        "schema": MANIFEST_SCHEMA,
        "kind": "pulse-corpus-selection",
        "variable": "deep-judge-gate-stage1-corpus",
        "timestamp": _utc_now_iso(),
        "pulse_version": _pulse_version(),
        "seed": seed,
        "corpus_dir": str(d),
        "redact_version": REDACT_VERSION,
        "prompt_version": PROMPT_VERSION,
        "counts": asdict(counts),
        "params": {
            "n_core": n_core,
            "n_enriched": n_enriched,
            "pair_floor": pair_floor,
            "floors_note": (
                "detector-positive floors enforced per comparable pair across the "
                "selection; judge-positive floors are a selection-report expectation "
                "re-checked at agreement time (not computable without judge calls)"
            ),
        },
        "judge": judge_identity,
        "items": items,
    }
    if out_path is not None:
        write_manifest(d, manifest, Path(out_path))
    return manifest


def write_manifest(corpus_dir: Path, manifest: dict[str, Any], out: Path) -> str:
    if out.suffix.lower() != ".json":
        raise CorpusError(f"manifest output must be a .json file path, got: {out}")
    out.parent.mkdir(parents=True, exist_ok=True)
    data = _canonical_bytes(manifest)
    out.write_bytes(data)
    return hashlib.sha256(data).hexdigest()


def default_manifest_path(corpus_dir: Path) -> Path:
    ts = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    return corpus_dir / "manifests" / f"manifest-{ts}.json"


__all__ = [
    "COMPARABLE_PAIRS",
    "MANIFEST_SCHEMA",
    "SNAPSHOT_SCHEMA",
    "CorpusError",
    "ExportSummary",
    "SchemaIncompatibleError",
    "SelectionCounts",
    "SelectionError",
    "approx_truncated",
    "default_manifest_path",
    "export_corpus",
    "load_active_snapshots",
    "read_index",
    "select_corpus",
    "snapshot_payload",
    "write_index",
    "write_manifest",
]
