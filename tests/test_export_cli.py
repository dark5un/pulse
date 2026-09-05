"""Tests for `pulse export` CLI (plan item 3 / B1)."""

import json

from pulse.export_cli import main


def _sidecar(d, name, sid, score, skills=()):
    rec = {
        "session_id": sid,
        "model": "m",
        "score": score,
        "penalty": 0,
        "cost_usd": 0.01,
        "task_type": "coding",
        "active_skills": list(skills),
        "signals": [],
        "path": str(d / f"{name}.py"),
    }
    (d / f"{name}.score.json").write_text(json.dumps(rec))


def _trace(d, name, text="please fix the login bug in auth.py today"):
    (d / f"{name}.py").write_text(
        f'SESSION_ID = "{name}"\nMODEL = "m"\nCOST = {{"cost_usd": 0.01}}\n'
        f"TIMELINE = [{{\"kind\": \"user_message\", \"text\": \"{text}\"}}]\n"
    )


def test_export_writes_files(tmp_path, capsys):
    d = tmp_path / "c"
    d.mkdir()
    _trace(d, "t1")
    _sidecar(d, "t1", "t1", 95)
    out = tmp_path / "out"
    assert main(["--corpus", str(d), "--out", str(out), "--min-score", "90"]) == 0
    assert (out / "sft.jsonl").exists()
    assert (out / "manifest.json").exists()
    assert "kept=1" in capsys.readouterr().out


def test_export_review_dumps_pairs(tmp_path, capsys):
    d = tmp_path / "c"
    d.mkdir()
    (d / "t1.py").write_text(
        'SESSION_ID = "t1"\nMODEL = "m"\nCOST = {"cost_usd": 0.01}\n'
        "TIMELINE = [\n"
        ' {"kind": "user_message", "text": "please write a sort function now"},\n'
        ' {"kind": "llm_call", "text": "here is bubble sort code today"},\n'
        ' {"kind": "user_message", "text": "no, use quicksort instead please"},\n'
        ' {"kind": "llm_call", "text": "here is quicksort code for you"},\n'
        "]\n"
    )
    _sidecar(d, "t1", "t1", 95)
    out = tmp_path / "out"
    assert main(["--corpus", str(d), "--out", str(out), "--review"]) == 0
    text = capsys.readouterr().out
    assert "REJECTED" in text and "CHOSEN" in text
