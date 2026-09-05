"""Tests for `pulse incident|flake` CLIs (plan item 5 / C1+C3)."""


def _trace(tmp_path, name, kinds):
    lines = [f'SESSION_ID = "{name}"', 'MODEL = "m"', 'COST = {"cost_usd": 0.01}',
             "TIMELINE = ["]
    for k in kinds:
        lines.append(f' {{"kind": "{k}", "offset_ms": 0}},')
    lines.append("]")
    p = tmp_path / f"{name}.py"
    p.write_text("\n".join(lines) + "\n")
    return str(p)


def test_incident_cli(tmp_path, capsys):
    from pulse.incident_cli import main

    trace = _trace(tmp_path, "t1", ["user_message", "tool_call", "llm_call"])
    assert main(["--trace", trace, "--bad-step", "1"]) == 0
    out = capsys.readouterr().out
    assert ">>>" in out and "counterfactual" in out


def test_flake_cli_single_trace(tmp_path, capsys):
    from pulse.incident_cli import flake_main

    trace = _trace(tmp_path, "t1", ["user_message"])
    assert flake_main(["--trace", trace, "--runs", "2"]) == 0
    assert "stable" in capsys.readouterr().out
