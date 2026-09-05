"""Tests for incident skeleton + flake runner (plan item 5 / C1+C3)."""

import subprocess


def _trace(tmp_path, name, kinds):
    lines = [f'SESSION_ID = "{name}"', 'MODEL = "m"', 'COST = {"cost_usd": 0.01}',
             "TIMELINE = ["]
    for k in kinds:
        lines.append(f' {{"kind": "{k}", "offset_ms": 0}},')
    lines.append("]")
    p = tmp_path / f"{name}.py"
    p.write_text("\n".join(lines) + "\n")
    return str(p)


def test_incident_skeleton_around_bad_step(tmp_path):
    from pulse.incident import skeleton

    trace = _trace(tmp_path, "t1", ["user_message", "tool_call", "tool_call",
                                    "tool_call", "llm_call"])
    out = skeleton(trace, bad_step=2, window=1)
    assert out["bad_step"] == 2
    assert len(out["timeline_window"]) == 3
    assert out["score_before"] >= 0 and out["score_after"] >= 0
    assert "counterfactual" in out
    assert "substitute-tool" in out["counterfactual"][0]


def test_incident_bad_step_out_of_range(tmp_path):
    from pulse.incident import skeleton

    trace = _trace(tmp_path, "t1", ["user_message"])
    try:
        skeleton(trace, bad_step=9)
    except ValueError as e:
        assert "out of range" in str(e)
    else:
        raise AssertionError("expected ValueError")


def test_step_signature_stable():
    from pulse.flake import step_signature

    assert step_signature({"kind": "tool_call", "name": "read"}) == \
        step_signature({"kind": "tool_call", "name": "read", "offset_ms": 99})
    assert step_signature({"kind": "a"}) != step_signature({"kind": "b"})


def test_flake_all_stable(tmp_path):
    from pulse.flake import flake

    trace = _trace(tmp_path, "t1", ["user_message", "tool_call"])
    rows = flake([trace, trace], timeout=30)
    assert len(rows) == 2
    assert all(r["stability"] == "2/2" for r in rows)
    assert all(r["verdict"] == "stable" for r in rows)


def test_flake_diverging_step_flagged(tmp_path):
    from pulse.flake import flake

    a = _trace(tmp_path, "a", ["user_message", "tool_call"])
    b = _trace(tmp_path, "b", ["user_message", "llm_call"])
    rows = flake([a, b], timeout=30)
    assert any(r["verdict"] == "flaky" for r in rows)
    flaky = next(r for r in rows if r["verdict"] == "flaky")
    assert flaky["diverging_steps"] == [1]


def test_flake_failed_replay_reported(tmp_path):
    from pulse.flake import flake

    bad = tmp_path / "bad.py"
    bad.write_text("import sys; sys.exit(1)\n")
    rows = flake([str(bad)], timeout=30)
    assert rows[0]["verdict"] == "replay-failed"


def test_flake_uses_dry_run_not_live(tmp_path, monkeypatch):
    import pulse.flake as flake_mod

    seen = {}

    def fake_run(cmd, **kw):
        seen["cmd"] = cmd
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    trace = _trace(tmp_path, "t1", ["user_message"])
    flake_mod.flake([trace], timeout=30)
    assert "--live" not in seen["cmd"]
