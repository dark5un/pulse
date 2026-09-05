"""Tests for `pulse costs` CLI (plan item 6 / C2-b)."""

import csv
import json


def _setup(tmp_path):
    d = tmp_path / "c"
    d.mkdir()
    (d / "t.py").write_text("x = 1\n")
    rec = {"session_id": "s1", "model": "m", "score": 90, "penalty": 10,
           "cost_usd": 0.05, "task_type": "coding", "signals": [],
           "path": str(d / "t.py")}
    (d / "t.score.json").write_text(json.dumps(rec))
    reg = tmp_path / "sessions.csv"
    with open(reg, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["session_id", "team"])
        w.writerow(["s1", "team-a"])
    return d, reg


def test_costs_cli_table(tmp_path, capsys):
    from pulse.costs_cli import main

    d, reg = _setup(tmp_path)
    assert main(["--corpus", str(d), "--join", str(reg)]) == 0
    out = capsys.readouterr().out
    assert "team-a" in out and "0.05" in out


def test_costs_cli_json(tmp_path, capsys):
    import json as j

    from pulse.costs_cli import main

    d, reg = _setup(tmp_path)
    assert main(["--corpus", str(d), "--join", str(reg), "--json"]) == 0
    assert j.loads(capsys.readouterr().out)["team-a"]["total_usd"] == 0.05


def test_costs_cli_group_by_task(tmp_path, capsys):
    from pulse.costs_cli import main

    d, reg = _setup(tmp_path)
    assert main(["--corpus", str(d), "--join", str(reg), "--group-by", "task"]) == 0
    assert "coding" in capsys.readouterr().out


def test_costs_cli_group_by_tag(tmp_path, capsys):
    import json as j

    from pulse.costs_cli import main

    d, reg = _setup(tmp_path)
    rec = j.loads((d / "t.score.json").read_text())
    rec["session_tags"] = ["team-a", "feat-x"]
    (d / "t.score.json").write_text(j.dumps(rec))
    assert main(["--corpus", str(d), "--join", str(reg), "--group-by", "tag"]) == 0
    out = capsys.readouterr().out
    assert "feat-x,team-a" in out


def test_costs_cli_group_by_tag_untagged(tmp_path, capsys):
    from pulse.costs_cli import main

    d, reg = _setup(tmp_path)
    assert main(["--corpus", str(d), "--join", str(reg), "--group-by", "tag"]) == 0
    assert "untagged" in capsys.readouterr().out
