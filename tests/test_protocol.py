import json
import subprocess
import sys
from pathlib import Path

import pytest

from pulse.protocol import analyze_document, parse_document, serialize_result
from pulse.scoring import score_penalties


def valid_document() -> dict:
    messages = []
    for i, role in enumerate(("user", "assistant", "user", "assistant", "user", "assistant")):
        messages.append({"id": str(i), "parent_id": str(i - 1) if i else None, "role": role,
                         "content": "Implement api.py" if role == "user" else "Done", "tool_calls": [],
                         "tool_error": False, "timestamp": 1730000000000 + i, "metadata": {}})
    return {"schema_version": 1, "harness": "pi", "session_id": "sid", "branch_leaf_id": "5",
            "session_file": None, "provider": "anthropic", "model": "claude", "messages": messages}


def test_valid_document_produces_versioned_result():
    result = analyze_document(parse_document(valid_document()))
    payload = json.loads(serialize_result(result))
    assert payload["schema_version"] == 1
    assert payload["status"] == "ok"
    assert payload["session_id"] == "sid"
    assert payload["message_count"] == 6
    assert 0 <= payload["score"] <= 100


def test_missing_required_field_is_rejected():
    document = valid_document()
    del document["branch_leaf_id"]
    with pytest.raises(ValueError, match="branch_leaf_id"):
        parse_document(document)


def test_malformed_json_cli_has_no_traceback_on_stdout(tmp_path: Path):
    proc = subprocess.run([sys.executable, "-m", "pulse", "analyze", "--json"], input="{bad\n",
                          text=True, capture_output=True, check=False)
    assert proc.returncode != 0
    assert proc.stdout == ""
    assert "traceback" not in proc.stderr.lower()


def test_fixture_excludes_sibling_branch():
    fixture = json.loads(Path("tests/fixtures/pi/branch.json").read_text())
    result = analyze_document(parse_document(fixture))
    assert result.message_count == 6
    assert all(message["id"] != "sibling" for message in parse_document(fixture).messages)


def test_stable_serialization():
    document = parse_document(valid_document())
    assert serialize_result(analyze_document(document)) == serialize_result(analyze_document(document))


def test_clean_document_has_zero_attribution():
    result = analyze_document(parse_document(valid_document()))
    assert result["attribution"] == {"user": 0.0, "agent": 0.0, "other": 0.0}


def test_user_only_penalty_is_fully_attributed_to_user():
    assert score_penalties({"user": 12.0}).attribution == {"user": 100.0, "agent": 0.0, "other": 0.0}


def test_non_clean_attribution_shares_sum_to_one_hundred():
    shares = score_penalties({"user": 1.0, "agent": 2.0, "other": 1.0}).attribution
    assert abs(sum(shares.values()) - 100.0) < 0.01


def test_explicit_tool_error_is_logged_with_tool_name():
    document = valid_document()
    document["messages"][3] = {"id": "tool", "role": "tool", "content": "permission denied",
                               "tool_name": "bash", "tool_error": True, "tool_calls": []}
    result = analyze_document(parse_document(document))
    assert result["runtime_logs"] == [{"module": "bash", "error": "permission denied", "severity": "info"}]
