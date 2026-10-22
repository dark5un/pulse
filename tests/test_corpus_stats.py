"""Deep-judge gate CW-9 (G2'): report-only detector stats.

Synthetic sessions only (fixtures reused from test_corpus); never real
transcripts.
"""

from __future__ import annotations

import hashlib
import json

import pytest
from test_corpus import (
    make_db,
    session_correcting,
    session_plain,
    session_stopping,
)

from pulse import corpus as cp
from pulse.corpus_cli import main as corpus_main

# ── CW-9 G2': report-only stats mode# ── CW-9 G2': report-only stats mode ─────────────────────────────────────


def test_detector_stats_reports_short_floors_without_raising(tmp_path):
    """--stats measures pools even where select() must refuse, writes no
    manifest, and relaxes nothing."""
    sessions = [session_correcting(f"c{i}") for i in range(12)] + [
        session_plain(f"p{i:03d}") for i in range(30)
    ] + [session_stopping(f"s{i}") for i in range(11)]
    db = make_db(tmp_path / "state.db", sessions)
    out = tmp_path / "corpus"
    cp.export_corpus(out, db_path=db)
    stats = cp.detector_stats(out, n_core=50, n_enriched=50, pair_floor=10)
    assert stats["eligible"] == 53
    assert stats["det_positive"]["correction_chain"] == {"pool": 12, "floor_met": True}
    assert stats["det_positive"]["premature_stop"] == {"pool": 11, "floor_met": True}
    assert stats["eligibility_met"] is False  # 53 < 100
    assert stats["manifest_producible"] is False
    assert not (out / "manifests").exists() or not list((out / "manifests").glob("*.json"))
    rc = corpus_main(["select", "--corpus", str(out), "--stats"])
    assert rc == 0
    assert not (out / "manifests").exists() or not list((out / "manifests").glob("*.json"))
    # plain select on the same corpus still refuses: stats relaxed nothing
    with pytest.raises(cp.SelectionError):
        cp.select_corpus(out, seed=1)


def test_detector_stats_uses_stamped_task_type_not_redetection(tmp_path):
    """Snapshots carry no tool_calls, so detect_task_type on the skeleton
    would misclassify a question-heavy coding session as brainstorm and
    gate correction_chain off. Stats must use the stamped task_type."""
    d = tmp_path / "corpus"
    d.mkdir()
    msgs = [
        {"role": "user", "content": "why is this wrong? where is the bug? what changed? who wrote it?"},
        {"role": "assistant", "content": "the parser module throws on line 12, fixing it now"},
        {"role": "user", "content": "and how do we know? did you test it? when did this start? why again?"},
        {"role": "assistant", "content": "patched the parser module and ran the suite"},
        {"role": "user", "content": "no, that's not it, revert the patch"},
    ]
    payload = {
        "schema": cp.SNAPSHOT_SCHEMA,
        "session_id": "s-q",
        "model": "test-model",
        "started_at": 1000.0,
        "ended_at": 2000.0,
        "task_type": "coding",  # stamped from the raw DB plane (tool_calls)
        "message_count": len(msgs),
        "messages": msgs,
        "redact_version": "test",
        "approx_truncated": False,
        "advisory": {
            "note": "stale",
            "pulse_version": "old",
            "det_signals": [],
            "det_pairs": {"correction_chain": 0, "premature_stop": 0},
        },
    }
    content = json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
    name = f"{digest[:16]}.json"
    (d / name).write_text(content, encoding="utf-8")
    cp.write_index(d, {name: {
        "sha256": digest,
        "session_id": "s-q",
        "model": "test-model",
        "task_type": "coding",
        "message_count": len(msgs),
        "approx_truncated": False,
        "redact_version": "test",
        "pulse_version": "old",
        "exported_at": "2026-01-01T00:00:00+00:00",
    }})
    # sanity: re-detecting task_type on this skeleton (no tool_calls) IS brainstorm
    from pulse.task_type import detect_task_type

    assert detect_task_type(msgs) == "brainstorm"
    stats = cp.detector_stats(d, pair_floor=10)
    assert stats["det_positive"]["correction_chain"]["pool"] == 1  # stamped coding wins


def test_detector_stats_recomputes_labels_despite_stale_advisory(tmp_path):
    """ML-B7 plane: stats recomputes via extract_signals from the snapshot
    messages; a stale all-zero advisory sidecar does not zero the pools."""
    d = tmp_path / "corpus"
    d.mkdir()
    msgs = session_stopping("s1")["messages"]
    payload = {
        "schema": cp.SNAPSHOT_SCHEMA,
        "session_id": "s1",
        "model": "test-model",
        "started_at": 1000.0,
        "ended_at": 2000.0,
        "task_type": "chat",
        "message_count": len(msgs),
        "messages": [{"role": m["role"], "content": m["content"]} for m in msgs],
        "redact_version": "test",
        "approx_truncated": False,
        "advisory": {
            "note": "exported by an older detector build",
            "pulse_version": "old",
            "det_signals": [],
            "det_pairs": {"correction_chain": 0, "premature_stop": 0},
        },
    }
    content = json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
    name = f"{digest[:16]}.json"
    (d / name).write_text(content, encoding="utf-8")
    cp.write_index(d, {name: {
        "sha256": digest,
        "session_id": "s1",
        "model": "test-model",
        "task_type": "chat",
        "message_count": len(msgs),
        "approx_truncated": False,
        "redact_version": "test",
        "pulse_version": "old",
        "exported_at": "2026-01-01T00:00:00+00:00",
    }})
    stats = cp.detector_stats(d, pair_floor=10)
    assert stats["det_positive"]["premature_stop"]["pool"] == 1  # recomputed
    assert stats["advisory_stale"] == 1
