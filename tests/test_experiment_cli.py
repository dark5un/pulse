"""Tests for `pulse experiment|bundle|verify` CLIs (plan item 4 / B3+B4)."""

import json


def _trace(d, name="t.py"):
    (d / f"{name}").write_text('SESSION_ID = "s1"\nMODEL = "m"\nTIMELINE = []\n')
    return d / name


def test_experiment_cli(tmp_path, capsys):
    from pulse.experiment_cli import main

    d = tmp_path / "c"
    d.mkdir()
    _trace(d)
    out = tmp_path / "exp"
    assert main(["--corpus", str(d), "--out", str(out), "--variable", "model=m2"]) == 0
    assert (out / "manifest.json").exists()
    assert "model=m2" in capsys.readouterr().out


def test_bundle_and_verify_cli(tmp_path, capsys):
    from pulse.artifact_cli import main as bundle_main
    from pulse.artifact_cli import verify_main

    d = tmp_path / "c"
    d.mkdir()
    trace = _trace(d)
    (d / "t.score.json").write_text(json.dumps({"score": 100, "penalty": 0}))
    assert bundle_main([str(trace), "--out", str(tmp_path / "art")]) == 0
    assert ".artifact" in capsys.readouterr().out
    assert verify_main([str(tmp_path / "art" / "t.artifact")]) == 0
    assert "score reproduces" in capsys.readouterr().out
