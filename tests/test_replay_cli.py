"""Tests for `pulse replay` CLI (plan item 1 / A1)."""

from pulse.replay_cli import find_traces, main, render_table


def _rec(score, task="coding"):
    return {"score": score, "task_type": task}


def test_find_traces_only_py(tmp_path):
    (tmp_path / "a.py").write_text("x = 1\n")
    (tmp_path / "a.score.json").write_text("{}")
    (tmp_path / "note.txt").write_text("hi")
    found = find_traces(str(tmp_path))
    assert found == [str(tmp_path / "a.py")]


def test_find_traces_missing_dir(tmp_path):
    try:
        find_traces(str(tmp_path / "nope"))
    except SystemExit as e:
        assert "not found" in str(e)
    else:
        raise AssertionError("expected SystemExit")


def test_render_table_marks_status():
    rows = [
        {"trace": "a.py", "ok": True, "returncode": 0, "timed_out": False, "output": ""},
        {"trace": "b.py", "ok": False, "returncode": 1, "timed_out": False, "output": ""},
        {"trace": "c.py", "ok": False, "returncode": -1, "timed_out": True, "output": ""},
    ]
    table = render_table(rows)
    assert "PASS" in table and "FAIL" in table and "TIMEOUT" in table
    assert "1/3" in table and "2 failed" in table


def test_render_table_json_roundtrip():
    import json

    rows = [{"trace": "a.py", "ok": True, "returncode": 0, "timed_out": False, "output": "x"}]
    assert json.loads(_json(rows))[0]["trace"] == "a.py"


def _json(rows):
    from pulse.replay_cli import render_json

    return render_json(rows)


def test_main_dry_run_on_stubs(tmp_path, capsys):
    (tmp_path / "ok.py").write_text('print("hi")\n')
    rc = main(["--corpus", str(tmp_path), "--jobs", "1"])
    assert rc == 0
    assert "PASS" in capsys.readouterr().out


def test_main_exit_nonzero_on_failure(tmp_path, capsys):
    (tmp_path / "bad.py").write_text("import sys; sys.exit(2)\n")
    rc = main(["--corpus", str(tmp_path), "--jobs", "1"])
    assert rc == 1
    assert "FAIL" in capsys.readouterr().out
