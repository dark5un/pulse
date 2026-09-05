"""WU-4 (PU-6, PU-7, PU-10): weights, canonical scoring, judge privacy.

- every real deep signal has a default weight entry that moves with
  feedback; deep_context_drift is gone (save() drops unknown keys).
- slash command, trace_score.score_bundle(), leaderboard, and artifact
  verification agree on one canonical result (golden fixture).
- judge key resolution honours HERMES_HOME, not ~/.hermes.
- build_prompt redacts secrets before construction; transcript bounded
  with documented truncation.
- CLI --deep prints an explicit outbound-data notice (opt-in remote call).
"""

import json


def _fixture_trace(tmp_path):
    p = tmp_path / "t.py"
    p.write_text(
        'SESSION_ID = "gold"\nMODEL = "m"\nPROVIDER = "p"\n'
        'TIMELINE = [{"kind": "user_message", "text": "please fix the login bug today"},\n'
        ' {"kind": "llm_call", "text": "patched auth.py with a regression test"}]\n'
        'USAGE = {}\nCOST = {"cost_usd": 0.01}\nACTIVE_SKILLS = []\n'
    )
    return p


def test_every_deep_signal_weight_moves():
    from pulse.signals_deep import DEEP_SIGNALS
    from pulse.weights import DEFAULT_WEIGHTS, record_feedback

    for signal in DEEP_SIGNALS:
        assert signal in DEFAULT_WEIGHTS, f"{signal} has no default weight"
        # Build from defaults directly to avoid HOME dependence.
        import copy

        weights = copy.deepcopy(DEFAULT_WEIGHTS)
        weights["_meta"] = {"total_feedback": 6}
        weights[signal] = {"penalty": 10.0, "useful": 3, "not_useful": 0}
        before = weights[signal]["penalty"]
        out = record_feedback(weights, signal, True)
        assert out[signal]["penalty"] != before


def test_deep_context_drift_removed_and_not_persisted(tmp_path):
    from pulse.weights import DEFAULT_WEIGHTS, load, save

    assert "deep_context_drift" not in DEFAULT_WEIGHTS
    target = tmp_path / "w.json"
    target.write_text(json.dumps({
        "deep_context_drift": {"penalty": 5, "useful": 0, "not_useful": 0},
        "correction_chain": {"penalty": 12, "useful": 0, "not_useful": 0},
    }))
    save(load(path=target), path=target)
    data = json.loads(target.read_text())
    assert "deep_context_drift" not in data


def test_canonical_scoring_agrees_everywhere(tmp_path):
    from pulse.artifact import bundle, verify
    from pulse.trace_score import score_bundle, score_trace_file
    from pulse.unroll_loader import bundle_to_messages, load_unroll_trace

    trace = _fixture_trace(tmp_path)
    via_file = score_trace_file(trace)
    loaded = load_unroll_trace(str(trace))
    via_bundle = score_bundle(loaded, bundle_to_messages(loaded))
    assert via_file["score"] == via_bundle["score"]
    assert via_file["penalty"] == via_bundle["penalty"]
    assert via_file["signals"] == via_bundle["signals"]
    # Slash-command path uses the same scorer.
    from pulse.scoring import score_penalties

    user_p = sum(s["penalty"] for s in via_bundle["signals"] if s["target"] == "user")
    agent_p = sum(s["penalty"] for s in via_bundle["signals"] if s["target"] == "agent")
    other_p = via_bundle["penalty"] - user_p - agent_p
    breakdown = score_penalties({"user": user_p, "agent": agent_p, "other": other_p})
    assert breakdown.score == via_bundle["score"]
    # Artifact verify rescores identically.
    dest = bundle(str(trace), out_dir=str(tmp_path / "art"))
    out = verify(dest)
    assert out["score_reproduces"] is True


def test_judge_key_resolution_honours_hermes_home(tmp_path, monkeypatch):

    from pulse import judge as judge_mod

    home = tmp_path / "profile"
    (home / ".hermes").mkdir(parents=True) if False else None
    home.mkdir()
    (home / ".env").write_text("OPENAI_API_KEY=sk-profile-key-123\n")
    monkeypatch.setenv("HERMES_HOME", str(home))
    for var in ("PULSE_API_KEY", "OPENAI_API_KEY", "HERMES_API_KEY"):
        monkeypatch.delenv(var, raising=False)
    # Point HOME elsewhere so a ~/.hermes fallback cannot satisfy the lookup.
    monkeypatch.setenv("HOME", str(tmp_path / "other"))
    assert judge_mod.resolve_api_key() == "sk-profile-key-123"


def test_build_prompt_redacts_secrets():
    from pulse.signals_deep import build_prompt

    prompt = build_prompt([
        {"role": "user", "content": "my key is sk-live-AAAAAAAA11111111 please"},
        {"role": "assistant", "content": "Authorization: Bearer abcdef1234567890XYZ"},
        {"role": "user", "content": "mail me at alice@example.com"},
    ])
    assert "sk-live-AAAAAAAA11111111" not in prompt
    assert "abcdef1234567890XYZ" not in prompt
    assert "alice@example.com" not in prompt


def test_build_prompt_bounded_with_truncation_note():
    from pulse.signals_deep import MAX_PROMPT_CHARS, build_prompt

    msgs = [{"role": "user", "content": "word " * 100} for _ in range(60)]
    prompt = build_prompt(msgs)
    assert len(prompt) <= MAX_PROMPT_CHARS + 500
    assert "truncat" in prompt.lower()


def test_deep_cli_prints_outbound_notice(tmp_path, capsys):
    import sys

    from pulse.__main__ import main

    f = tmp_path / "s.jsonl"
    f.write_text(
        '{"role": "user", "content": "hello world today please"}\n'
        '{"role": "assistant", "content": "hi there friend, all good today"}\n'
    )
    old_argv = sys.argv
    try:
        sys.argv = ["pulse", "--file", str(f), "--deep", "--judge-model", "no-such-model",
                    "--judge-base-url", "http://127.0.0.1:1"]
        try:
            main()
        except SystemExit:
            pass
    finally:
        sys.argv = old_argv
    out = capsys.readouterr().out
    assert "sends transcript" in out.lower() or "transcript" in out.lower()
