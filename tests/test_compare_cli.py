"""Tests for `pulse compare` CLI (plan item 2 / A2)."""

from pulse.compare_cli import main, render


def _rec(score, cost=0.01):
    return {"score": score, "cost_usd": cost, "task_type": "coding"}


def test_render_shows_verdict_and_table():
    out = render([_rec(90)], [_rec(80)], "A", "B")
    assert "A wins" in out
    assert "mean" in out and "p25" in out


def test_render_json_roundtrip():
    import json

    from pulse.compare_cli import render_json

    d = json.loads(render_json([_rec(90)], [_rec(80)], "A", "B"))
    assert d["score_delta"] == 10.0
    assert "verdict" in d


def test_main_two_corpora(tmp_path, capsys):
    import json

    for name in ("a", "b"):
        d = tmp_path / name
        d.mkdir()
        (d / "t.py").write_text("x = 1\n")
        rec = {"session_id": name, "model": "m", "score": 90 if name == "a" else 80,
               "penalty": 10, "cost_usd": 0.01, "task_type": "coding",
               "signals": [], "path": str(d / "t.py")}
        (d / "t.score.json").write_text(json.dumps(rec))
    rc = main(["--a", str(tmp_path / "a"), "--b", str(tmp_path / "b")])
    assert rc == 0
    assert "A wins" in capsys.readouterr().out
