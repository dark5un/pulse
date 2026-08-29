import json
import subprocess
import sys
from pathlib import Path

import pytest

from pulse.protocol import analyze_document, parse_document, serialize_result


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
