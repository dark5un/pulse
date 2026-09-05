"""Tests for `pulse skills` CLI (plan item 2b / A3)."""

import json

from pulse.skills_cli import main, render


def _rec(skills, score=85):
    return {
        "session_id": f"{skills}-{score}",
        "model": "m",
        "score": score,
        "penalty": 15,
        "cost_usd": 0.02,
        "task_type": "coding",
        "active_skills": list(skills),
        "signals": [],
        "path": "t.py",
    }


def test_render_table_shows_rates_and_mix():
    rows = render([_rec(["skill-a"]), _rec([])])
    assert "skill-a" in rows
    assert "loads" in rows and "task_mix" in rows


def test_render_empty():
    assert "No skill data" in render([_rec([])])


def test_render_json_roundtrip():
    from pulse.skills_cli import render_json

    d = json.loads(render_json([_rec(["skill-a"])]))
    assert d["skill-a"]["loads"] == 1


def test_main_on_tmp_corpus(tmp_path, capsys):
    d = tmp_path / "c"
    d.mkdir()
    (d / "t.py").write_text("x = 1\n")
    (d / "t.score.json").write_text(json.dumps(_rec(["skill-a"])))
    assert main(["--corpus", str(d)]) == 0
    assert "skill-a" in capsys.readouterr().out
