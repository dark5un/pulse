"""Tests for pulse export (plan item 3 / B1). Synthetic bundles only."""

import json

from pulse.export import bundle_to_sharegpt, correction_pairs, export_records


def _bundle():
    from pulse.unroll_loader import UnrollBundle

    return UnrollBundle(
        session_id="sess-1",
        model="m1",
        provider="p",
        timeline=[
            {"kind": "user_message", "text": "please fix the login bug"},
            {"kind": "llm_call", "text": "the bug is in auth.py line 5"},
            {"kind": "tool_call", "name": "read_file", "args": {"path": "auth.py"}},
            {"kind": "user_message", "text": "no, fix it properly this time"},
            {"kind": "llm_call", "text": "patched auth.py with a regression test"},
        ],
        cost_usd=0.01,
        active_skills=[],
    )


def _msgs():
    return [
        {"role": "user", "content": "please fix the login bug"},
        {"role": "assistant", "content": "the bug is in auth.py line 5"},
        {"role": "tool", "content": "read_file"},
        {"role": "user", "content": "no, fix it properly this time"},
        {"role": "assistant", "content": "patched auth.py with a regression test"},
    ]


def test_bundle_to_sharegpt_roles_and_tool_calls():
    msgs = bundle_to_sharegpt(_bundle())
    roles = [m["role"] for m in msgs]
    assert roles == ["user", "assistant", "tool", "user", "assistant"]
    tool_msgs = [m for m in msgs if m["role"] == "tool"]
    assert tool_msgs[0]["name"] == "read_file"
    assert tool_msgs[0]["content"]
    # no empty-content messages leak into training data
    assert all(m["content"] for m in msgs)


def test_bundle_to_sharegpt_skips_textless_timeline_entries():
    from pulse.unroll_loader import UnrollBundle

    b = UnrollBundle(
        session_id="s", timeline=[{"kind": "pre_api_request", "offset_ms": 1}]
    )
    assert bundle_to_sharegpt(b) == []


def test_correction_pairs_rejected_is_pre_correction():
    pairs = correction_pairs(_msgs())
    assert len(pairs) == 1
    assert pairs[0]["rejected"] == "the bug is in auth.py line 5"
    assert pairs[0]["chosen"] == "patched auth.py with a regression test"
    assert "no, fix it properly" in pairs[0]["correction"]


def test_correction_pairs_no_correction_no_pairs():
    msgs = [
        {"role": "user", "content": "please write a poem about rust"},
        {"role": "assistant", "content": "here is a poem"},
    ]
    assert correction_pairs(msgs) == []


def test_export_records_manifest_and_filters(tmp_path):
    from pulse.trace_score import score_bundle

    rec_hi = score_bundle(_bundle())
    rec_hi["score"] = 95
    rec_lo = dict(rec_hi, score=10, session_id="bad")
    manifest = export_records(
        [rec_hi, rec_lo],
        messages_by_id={"sess-1": _msgs(), "bad": []},
        out_dir=str(tmp_path),
        fmt="sharegpt",
        min_score=90,
    )
    assert manifest["kept"] == 1 and manifest["dropped"] == 1
    assert manifest["redaction_receipt"] == "redacted-at-capture"
    sft_file = tmp_path / "sft.jsonl"
    assert sft_file.exists()
    rows = [json.loads(line) for line in sft_file.read_text().splitlines()]
    assert rows[0]["messages"][0]["role"] == "user"
    pairs_file = tmp_path / "pairs.jsonl"
    assert pairs_file.exists()
    assert json.loads(pairs_file.read_text().splitlines()[0])["chosen"]
