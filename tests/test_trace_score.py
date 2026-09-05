"""Tests for shared trace scorer (Phase A)."""

from pathlib import Path

from pulse.trace_score import anonymize, score_bundle, score_trace_file


def _bundle():
    from pulse.unroll_loader import UnrollBundle

    return UnrollBundle(
        session_id="sess-abc-123",
        model="m1",
        provider="p",
        timeline=[
            {"kind": "user_message", "text": "hello, please help me debug this"},
            {"kind": "llm_call", "text": "sure, here is some help with lots of words " * 10},
        ],
        cost_usd=0.01,
        active_skills=[],
    )


def test_anonymize_is_sha256_prefix():
    import hashlib

    assert anonymize("sess-abc-123") == hashlib.sha256(b"sess-abc-123").hexdigest()[:12]


def test_score_bundle_keys_and_score_math():
    from pulse.unroll_loader import bundle_to_messages

    bundle = _bundle()
    rec = score_bundle(bundle, bundle_to_messages(bundle))
    for key in ("session_id", "model", "score", "penalty", "cost_usd", "task_type", "signals"):
        assert key in rec
    assert rec["score"] == max(0, min(100, round(100 - rec["penalty"])))
    assert rec["session_id"] == "sess-abc-123"
    assert rec["model"] == "m1"


def test_score_trace_file_on_real_corpus():
    corpus = sorted(Path("corpus").glob("*.py"))
    assert corpus, "expected local corpus traces"
    rec = score_trace_file(corpus[0])
    assert rec["score"] >= 0
    # byte-identical check: matches existing sidecar score
    import json

    sidecar = json.loads((corpus[0].parent / (corpus[0].stem + ".score.json")).read_text())
    assert rec["score"] == sidecar["score"]
    assert rec["penalty"] == sidecar["penalty"]
