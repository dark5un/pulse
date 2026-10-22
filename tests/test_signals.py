"""
Litmus tests for Pulse signal detectors.

Every test is a deterministic pass/fail on a known input/output pair.
No thresholds, no ambiguity, no speculation.
If a test fails, either the signal detector is wrong OR the contract has changed.
"""


from pulse.constants import (
    TASK_BRAINSTORM,
)
from pulse.signals import extract_signals
from pulse.task_type import detect_task_type

# ─── Task Type Detection ──────────────────────────────────────────────────────

def test_detect_brainstorm_from_high_question_density():
    msgs = [
        {"role": "user", "content": "how would we approach this? what about that? why not?"},
        {"role": "user", "content": "could we do X? or maybe Y? what do you think?"},
        {"role": "user", "content": "should we use approach A B or C?"},
    ]
    assert detect_task_type(msgs) == TASK_BRAINSTORM


def test_detect_coding_from_writes():
    msgs = [
        {"role": "user", "content": "write the function"},
        {"role": "assistant", "content": "", "tool_calls": [{"function": {"name": "write_file"}}]},
    ]
    assert detect_task_type(msgs) == "coding"


def test_detect_research_from_web_tools():
    msgs = [
        {"role": "user", "content": "search for papers on X"},
        {"role": "assistant", "content": "", "tool_calls": [{"function": {"name": "web_search"}}]},
        {"role": "user", "content": "also check this url"},
        {"role": "assistant", "content": "", "tool_calls": [{"function": {"name": "web_extract"}}]},
    ]
    assert detect_task_type(msgs) == "research"


def test_detect_chat_no_tools():
    msgs = [
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": "hi there"},
        {"role": "user", "content": "what's the weather like?"},
        {"role": "assistant", "content": "I can't check that but I can chat"},
    ]
    assert detect_task_type(msgs) == "chat"


# ─── Edge Case: Too Short ─────────────────────────────────────────────────────

def test_skip_session_under_3_user_turns():
    msgs = [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "hello"},
        {"role": "user", "content": "build X"},
    ]
    # Only 2 user turns — must skip
    result = extract_signals(msgs, "chat")
    assert result.skipped_reason == "insufficient_data"


def test_skip_session_under_5_messages():
    msgs = [
        {"role": "user", "content": "build X"},
        {"role": "assistant", "content": "ok"},
        {"role": "tool", "content": "result"},
        {"role": "assistant", "content": "done"},
    ]
    # Only 4 messages — must skip
    result = extract_signals(msgs, "coding")
    assert result.skipped_reason == "insufficient_data"


# ─── Correction Chain ─────────────────────────────────────────────────────────

def test_correction_chain_detected_at_3_consecutive():
    msgs = [
        {"role": "user", "content": "build a search feature"},
        {"role": "assistant", "content": "here's the code"},
        {"role": "user", "content": "no, that's wrong"},
        {"role": "assistant", "content": "fixed it"},
        {"role": "user", "content": "no, still not right"},
        {"role": "assistant", "content": "changed again"},
        {"role": "user", "content": "no, that's not what I meant"},
    ]
    result = extract_signals(msgs, "coding")
    names = [s.name for s in result.signals]
    assert "correction_chain" in names, "3 consecutive 'no' corrections must fire correction_chain"


def test_correction_chain_not_detected_for_single_correction():
    msgs = [
        {"role": "user", "content": "build a search feature"},
        {"role": "assistant", "content": "here's the code"},
        {"role": "user", "content": "no, that's wrong, use whoosh instead"},
        {"role": "assistant", "content": "ok, using whoosh"},
        {"role": "user", "content": "great, now add filters"},
    ]
    result = extract_signals(msgs, "coding")
    names = [s.name for s in result.signals]
    assert "correction_chain" not in names, "single correction not a chain"


def test_correction_chain_does_not_fire_on_brainstorm_no():
    msgs = [
        {"role": "user", "content": "no, I was thinking more of X instead"},
        {"role": "assistant", "content": "interesting approach"},
        {"role": "user", "content": "no wait, Y might work better"},
    ]
    result = extract_signals(msgs, "brainstorm")
    names = [s.name for s in result.signals]
    assert "correction_chain" not in names, "brainstorm 'no' is not correction"


def test_correction_trigger_words_start_of_turn_only():
    """'no' in the middle of a sentence is not a correction."""
    msgs = [
        {"role": "user", "content": "I considered no but decided yes"},
        {"role": "assistant", "content": "ok"},
        {"role": "user", "content": "this has no relevance to what we're doing"},
    ]
    result = extract_signals(msgs, "chat")
    # correction_chain should not fire because 'no' is not at start
    corrections = [s for s in result.signals if s.name == "correction_chain"]
    assert len(corrections) == 0


# ── ADR 0018: user-turn-space adjacency truth table ───────────────────────

def _alternating(u: list[str]) -> list[dict]:
    """user/assistant alternation from a list of user texts."""
    msgs: list[dict] = []
    for text in u:
        msgs.append({"role": "user", "content": text})
        msgs.append({"role": "assistant", "content": "ok, continuing the work"})
    return msgs


def test_correction_chain_fires_across_agent_replies():
    """THE structurally-fireable shape: flagged turns separated by normal
    assistant rows. The old raw-adjacency detector could never see this."""
    msgs = _alternating([
        "build the parser feature",
        "no, that's not the file I meant",
        "still broken?",
        "you didn't update the config, redo it",
    ])
    result = extract_signals(msgs, "coding")
    names = [s.name for s in result.signals]
    assert "correction_chain" in names, "2 flagged turns in a 3-user-turn window must fire"


def test_correction_chain_window_edge_gap_two_fires():
    """Flagged turns 2 apart in turn space (distance-3 window) -> fires."""
    msgs = _alternating([
        "wrong, start from the schema again",
        "and add the index while you are in there",
        "that's not what I asked for",
    ])
    result = extract_signals(msgs, "coding")
    assert "correction_chain" in [s.name for s in result.signals]


def test_correction_chain_window_edge_gap_three_not_fired():
    """Flagged turns 3 apart (outside every 3-turn window) -> no fire."""
    msgs = _alternating([
        "wrong, start from the schema again",
        "and add the index while you are in there",
        "also update the readme",
        "that's not what I asked for",
    ])
    result = extract_signals(msgs, "coding")
    assert "correction_chain" not in [s.name for s in result.signals]


def test_correction_chain_contains_markers_flag_mid_turn():
    """Generic marker anywhere in the turn (not just start-of-turn)."""
    msgs = _alternating([
        "please use the whoosh library instead",
        "the loader is broken, please undo that patch",
        "now add pagination to the results page",
    ])
    result = extract_signals(msgs, "coding")
    assert "correction_chain" in [s.name for s in result.signals]


def test_correction_chain_word_boundary_no_false_flag():
    """'wrongly' must not match the 'wrong' marker; no other flags -> no fire."""
    msgs = _alternating([
        "the test wrongly asserts equality, fix it please",
        "thanks, now add pagination",
        "and sort the results by date",
    ])
    result = extract_signals(msgs, "chat")
    assert "correction_chain" not in [s.name for s in result.signals]


def test_correction_chain_evidence_quotes_flagged_turns():
    msgs = _alternating([
        "no, that's not the file I meant",
        "still broken?",
        "you didn't update the config, redo it",
    ])
    result = extract_signals(msgs, "coding")
    sigs = [s for s in result.signals if s.name == "correction_chain"]
    assert len(sigs) == 1
    assert any("that's not the file" in ev for ev in sigs[0].evidence)
    assert any("redo it" in ev for ev in sigs[0].evidence)
    assert sigs[0].penalty == 12
    assert sigs[0].severity == "warning"
    assert sigs[0].target == "user"


def test_correction_chain_regression_raw_adjacency_still_fires():
    """Old-shape anomaly (3 raw-consecutive user rows, no reply between)
    still fires under the user-turn-space construct."""
    msgs = [
        {"role": "user", "content": "build a search feature"},
        {"role": "assistant", "content": "here's the code"},
        {"role": "user", "content": "no, that's wrong"},
        {"role": "user", "content": "no, still not right"},
        {"role": "user", "content": "no, that's not what I meant"},
        {"role": "assistant", "content": "reverting now"},
    ]
    result = extract_signals(msgs, "coding")
    assert "correction_chain" in [s.name for s in result.signals]


# ─── Frustration ──────────────────────────────────────────────────────────────

def test_frustration_detected_in_multiple_turns():
    msgs = [
        {"role": "user", "content": "build a search feature"},
        {"role": "assistant", "content": "here's code"},
        {"role": "user", "content": "you're so lazy, do it properly"},
                    {"role": "assistant", "content": "I'll fix it"},
                    {"role": "user", "content": "you're not listening either"},
    ]
    result = extract_signals(msgs, "coding")
    names = [s.name for s in result.signals]
    assert "frustration" in names


def test_frustration_not_detected_for_direct_but_calm_correction():
    msgs = [
        {"role": "user", "content": "this is not correct, use the whoosh library instead"},
        {"role": "assistant", "content": "ok"},
        {"role": "user", "content": "also add rate limiting"},
    ]
    result = extract_signals(msgs, "coding")
    names = [s.name for s in result.signals]
    assert "frustration" not in names, "direct but calm correction is not frustration"


def test_frustration_not_detected_single_word():
    """'wrong' appearing once in a long prompt is not frustration."""
    msgs = [
        {"role": "user", "content": "I think the approach was wrong but let me reconsider"},
        {"role": "user", "content": "actually scratch that, do X instead"},
    ]
    result = extract_signals(msgs, "brainstorm")
    names = [s.name for s in result.signals]
    assert "frustration" not in names


# ─── Reasoning Loop ───────────────────────────────────────────────────────────

def test_reasoning_loop_detected_multiple_in_one_turn():
    msgs = [
        {"role": "user", "content": "build a search feature"},
        {"role": "assistant", "content": "Ok, I'll look at the code first"},
        {"role": "user", "content": "use fuzzy matching"},
        {"role": "assistant", "content": "Oh wait, actually, let me reconsider. Hmm, actually, no wait."},
        {"role": "user", "content": "proceed with what you have"},
    ]
    result = extract_signals(msgs, "coding")
    names = [s.name for s in result.signals]
    assert "reasoning_loop" in names, "3+ loop markers in one turn must fire"


def test_reasoning_loop_not_detected_single_hesitation():
    msgs = [
        {"role": "assistant", "content": "Actually, I think the answer is 42."},
    ]
    result = extract_signals(msgs, "coding")
    names = [s.name for s in result.signals]
    assert "reasoning_loop" not in names, "single 'actually' is not a loop"


# ─── Goal Drift ───────────────────────────────────────────────────────────────

def test_goal_drift_detected_in_brainstorm():
    """In brainstorm mode, goal drift should NOT fire."""
    msgs = [
        {"role": "user", "content": "what if we tried approach X?"},
        {"role": "assistant", "content": "that could work"},
        {"role": "user", "content": "different approach: what about Y instead?"},
    ]
    result = extract_signals(msgs, "brainstorm")
    names = [s.name for s in result.signals]
    assert "goal_drift" not in names, "goal drift should not fire in brainstorm"


def test_goal_drift_detected_in_coding():
    """In coding mode, goal drift SHOULD fire."""
    msgs = [
        {"role": "user", "content": "build a search feature using elasticsearch"},
        {"role": "assistant", "content": "ok, setting up elasticsearch"},
        {"role": "user", "content": "different approach: scrap that, use postgres instead"},
        {"role": "assistant", "content": "ok, switching to postgres"},
        {"role": "user", "content": "never mind, let's start over with mongodb"},
    ]
    result = extract_signals(msgs, "coding")
    names = [s.name for s in result.signals]
    assert "goal_drift" in names, "multiple direction changes in coding must fire"


# ─── Premature Stop (ADR 0018: claim-tail + continuation) ────────────────────

def test_premature_stop_claim_tail_plus_continuation():
    msgs = [
        {"role": "user", "content": "write the exporter for data.csv"},
        {"role": "assistant", "content": "working on the exporter now"},
        {"role": "user", "content": "also handle the json branch"},
        {"role": "assistant", "content": "The exporter handles csv and json, all set"},
        {"role": "user", "content": "continue, add the tests as well"},
        {"role": "assistant", "content": "Added tests for both branches"},
    ]
    result = extract_signals(msgs, "coding")
    sigs = [s for s in result.signals if s.name == "premature_stop"]
    assert len(sigs) == 1, "claim in turn tail + continuation in 1 turn -> fires"
    assert any("all set" in ev for ev in sigs[0].evidence)
    assert any("continue, add the tests" in ev for ev in sigs[0].evidence)
    assert sigs[0].penalty == 10
    assert sigs[0].severity == "warning"
    assert sigs[0].target == "agent"


def test_premature_stop_claim_outside_tail_not_fired():
    """'done' far from the turn end is mid-prose, not a closing claim."""
    filler = (
        " the parser now reads config files correctly, the tokenizer keeps "
        "its fast path, and the cache layer stays untouched through the run,"
    ) * 3
    msgs = [
        {"role": "user", "content": "explain the parser internals"},
        {"role": "assistant", "content": "the old spike is done, I will not touch it again." + filler},
        {"role": "user", "content": "continue with the tokenizer section"},
        {"role": "assistant", "content": "next part" + filler},
        {"role": "user", "content": "ok thanks for the overview breakdown"},
    ]
    result = extract_signals(msgs, "coding")
    assert "premature_stop" not in [s.name for s in result.signals]


def test_premature_stop_without_continuation_not_fired():
    """A completion claim nobody overrides is not a premature stop."""
    msgs = [
        {"role": "user", "content": "write the exporter for data.csv"},
        {"role": "assistant", "content": "working on it now"},
        {"role": "user", "content": "also handle json"},
        {"role": "assistant", "content": "Done, both formats are handled"},
        {"role": "user", "content": "nice, commit it please"},
    ]
    result = extract_signals(msgs, "coding")
    assert "premature_stop" not in [s.name for s in result.signals]


def test_premature_stop_continuation_outside_window_not_fired():
    """Continuation arriving 3 user turns after the claim misses the window."""
    msgs = [
        {"role": "user", "content": "write the exporter"},
        {"role": "assistant", "content": "Done, exporter is ready"},
        {"role": "user", "content": "add a cli flag for it"},
        {"role": "assistant", "content": "added the flag"},
        {"role": "user", "content": "update the docs"},
        {"role": "assistant", "content": "docs updated"},
        {"role": "user", "content": "continue with packaging too"},
    ]
    result = extract_signals(msgs, "coding")
    assert "premature_stop" not in [s.name for s in result.signals]


def test_premature_stop_word_boundaries_hold():
    """'abandoned' must not match 'done'; 'incomplete' must not match 'complete'."""
    msgs = [
        {"role": "user", "content": "what happened to the migration"},
        {"role": "assistant", "content": "the old table was simply abandoned mid-migration"},
        {"role": "user", "content": "go on with the next module then"},
        {"role": "assistant", "content": "moving to the next module now"},
        {"role": "user", "content": "thanks, that covers it"},
    ]
    result = extract_signals(msgs, "coding")
    assert "premature_stop" not in [s.name for s in result.signals]


def test_premature_stop_legacy_phrase_still_fires():
    """Legacy stop-offer phrasing survives as a tail claim when the user
    actually pushes back (old shape without continuation stays silent)."""
    msgs = [
        {"role": "user", "content": "draft the release notes"},
        {"role": "assistant", "content": "notes drafted for the api changes"},
        {"role": "user", "content": "and the bug fixes"},
        {"role": "assistant", "content": "Added the fixes section. Should I continue with the appendix?"},
        {"role": "user", "content": "yes, continue with the appendix"},
    ]
    result = extract_signals(msgs, "coding")
    assert "premature_stop" in [s.name for s in result.signals]


def test_premature_stop_not_fired_on_brainstorm_or_research():
    msgs = [
        {"role": "user", "content": "brainstorm feature directions for the app"},
        {"role": "assistant", "content": "here are three directions"},
        {"role": "user", "content": "and more options"},
        {"role": "assistant", "content": "also possible: a plugin system, all set as ideas"},
        {"role": "user", "content": "continue listing possibilities"},
    ]
    for tt in ("brainstorm", "research"):
        result = extract_signals(msgs, tt)
        assert "premature_stop" not in [s.name for s in result.signals], tt


# ─── Tool Repetition ──────────────────────────────────────────────────────────

def test_tool_repetition_detected():
    msgs = [
        {"role": "user", "content": "refactor the codebase"},
        {"role": "assistant", "content": "", "tool_calls": [
            {"function": {"name": "read_file"}}]},
        {"role": "user", "content": "continue"},
        {"role": "assistant", "content": "", "tool_calls": [
            {"function": {"name": "read_file"}}]},
        {"role": "user", "content": "more"},
        {"role": "assistant", "content": "", "tool_calls": [
            {"function": {"name": "read_file"}}]},
        {"role": "user", "content": "keep going"},
        {"role": "assistant", "content": "", "tool_calls": [
            {"function": {"name": "read_file"}}]},
    ]
    result = extract_signals(msgs, "coding")
    names = [s.name for s in result.signals]
    assert "tool_repetition" in names, "4 consecutive same tool must fire"


def test_tool_repetition_not_detected_for_diverse_tools():
    msgs = [
        {"role": "assistant", "content": "", "tool_calls": [
            {"function": {"name": "read_file"}}]},
        {"role": "assistant", "content": "", "tool_calls": [
            {"function": {"name": "grep"}}]},
        {"role": "assistant", "content": "", "tool_calls": [
            {"function": {"name": "write_file"}}]},
    ]
    result = extract_signals(msgs, "coding")
    names = [s.name for s in result.signals]
    assert "tool_repetition" not in names


# ─── Prompt Specificity ───────────────────────────────────────────────────────

def test_vague_prompts_flagged_on_coding():
    msgs = [
        {"role": "user", "content": "fix it"},
        {"role": "assistant", "content": "ok"},
        {"role": "user", "content": "make it better"},
        {"role": "assistant", "content": "how?"},
        {"role": "user", "content": "just do it"},
    ]
    result = extract_signals(msgs, "coding")
    names = [s.name for s in result.signals]
    assert "vague_prompts" in names


def test_vague_prompts_not_flagged_on_specific_code_requests():
    msgs = [
        {"role": "user", "content": "add rate limiting to api/users.py using flask-limiter"},
        {"role": "assistant", "content": "ok"},
        {"role": "user", "content": "also add redis backend for rate limiter in config.py"},
    ]
    result = extract_signals(msgs, "coding")
    names = [s.name for s in result.signals]
    assert "vague_prompts" not in names


def test_tool_error_not_fired_on_successful_output():
    """'All checks passed' followed by an 'error:' later should NOT fire."""
    msgs = [
        {"role": "user", "content": "run the tests"},
        {"role": "assistant", "content": "", "tool_calls": [
            {"function": {"name": "terminal"}}]},
        {"role": "user", "content": "what happened?"},
        {"role": "assistant", "content": "let me check"},
        {"role": "user", "content": "ok"},
        {"role": "tool", "content": "All checks passed!\n---\nerror: Failed to spawn: pytest\n  Caused by: No such file or directory"},
    ]
    result = extract_signals(msgs, "coding")
    names = [s.name for s in result.signals]
    assert "tool_error" not in names, "successful output with 'error:' in middle should not fire"


def test_tool_error_fired_on_genuine_failure():
    """Output starting with 'Error:' should be logged as a runtime error, not a signal."""
    msgs = [
        {"role": "user", "content": "run the build"},
        {"role": "assistant", "content": "", "tool_calls": [
            {"function": {"name": "terminal"}}]},
        {"role": "user", "content": "what happened?"},
        {"role": "assistant", "content": "let me check"},
        {"role": "user", "content": "ok"},
        {"role": "tool", "content": "Error: can only create exec sessions on running containers: container state improper"},
    ]
    result = extract_signals(msgs, "coding")
    # Should NOT be a signal (penalty)
    names = [s.name for s in result.signals]
    assert "tool_error" not in names, "tool_error should not be a signal"
    # Should be a runtime log
    assert len(result.runtime_logs) >= 1, "should have at least one runtime log"
    assert "Error:" in result.runtime_logs[0].error, "runtime log should contain the error"
    assert result.runtime_logs[0].module == "terminal", "should identify the source module"


def test_tool_error_not_fired_on_pyright_diagnostics():
    """Pyright diagnostics with 'error:' mid-output should NOT fire."""
    msgs = [
        {"role": "user", "content": "check test"},
        {"role": "assistant", "content": "", "tool_calls": [
            {"function": {"name": "terminal"}}]},
        {"role": "user", "content": "what happened?"},
        {"role": "assistant", "content": "let me check"},
        {"role": "user", "content": "ok"},
        {"role": "tool", "content": "/path/to/file.py:10:6 - warning: Import could not be resolved\n0 errors, 2 warnings\nerror: Failed to spawn: pytest\n  Caused by: No such file"},
    ]
    result = extract_signals(msgs, "coding")
    names = [s.name for s in result.signals]
    assert "tool_error" not in names, "pyright output with error mid-line should not fire"


def test_tool_error_not_fired_on_git_commit_output():
    """Git commit output with 'ERROR:' in the middle should NOT fire."""
    msgs = [
        {"role": "user", "content": "push changes"},
        {"role": "assistant", "content": "", "tool_calls": [
            {"function": {"name": "terminal"}}]},
        {"role": "user", "content": "what happened?"},
        {"role": "assistant", "content": "let me check"},
        {"role": "user", "content": "ok"},
        {"role": "tool", "content": "[main abc1234] Add feature\n 1 file changed, 42 insertions(+)\nERROR: Repository not found.\nfatal: Could not read from remote repository."},
    ]
    result = extract_signals(msgs, "coding")
    names = [s.name for s in result.signals]
    assert "tool_error" not in names, "git output with ERROR: mid-output should not fire"


def test_short_prompt_not_penalized_if_enough_context():
    """An expert developer might write short prompts in a known codebase.
    If the prompt has file paths or identifiers, don't penalize."""
    msgs = [
        {"role": "user", "content": "refactor auth.py to use async"},
    ]
    result = extract_signals(msgs, "coding")
    names = [s.name for s in result.signals]
    assert "vague_prompts" not in names, "short prompt with file path + term is specific enough"


# ─── Read:Edit Ratio ──────────────────────────────────────────────────────────

def test_shallow_read_detected():
    msgs = [
        {"role": "user", "content": "refactor the code"},
        {"role": "assistant", "content": "", "tool_calls": [
            {"function": {"name": "write_file"}}]},
        {"role": "user", "content": "more changes"},
        {"role": "assistant", "content": "", "tool_calls": [
            {"function": {"name": "write_file"}}]},
        {"role": "user", "content": "keep going"},
        {"role": "assistant", "content": "", "tool_calls": [
            {"function": {"name": "write_file"}}]},
    ]
    result = extract_signals(msgs, "coding")
    names = [s.name for s in result.signals]
    # 0 reads, 3 writes = 0 ratio < 2.0
    assert "shallow_read" in names


def test_deep_read_ok():
    msgs = [
        {"role": "user", "content": "refactor the code"},
        {"role": "assistant", "content": "", "tool_calls": [
            {"function": {"name": "read_file"}}]},
        {"role": "user", "content": "continue"},
        {"role": "assistant", "content": "", "tool_calls": [
            {"function": {"name": "read_file"}}]},
        {"role": "user", "content": "continue"},
        {"role": "assistant", "content": "", "tool_calls": [
            {"function": {"name": "read_file"}}]},
        {"role": "user", "content": "continue"},
        {"role": "assistant", "content": "", "tool_calls": [
            {"function": {"name": "read_file"}}]},
        {"role": "user", "content": "continue"},
        {"role": "assistant", "content": "", "tool_calls": [
            {"function": {"name": "read_file"}}]},
        {"role": "user", "content": "continue"},
        {"role": "assistant", "content": "", "tool_calls": [
            {"function": {"name": "read_file"}}]},
        {"role": "user", "content": "now write it"},
        {"role": "assistant", "content": "", "tool_calls": [
            {"function": {"name": "write_file"}}]},
    ]
    result = extract_signals(msgs, "coding")
    names = [s.name for s in result.signals]
    assert "shallow_read" not in names, "6 reads, 1 write = 6.0 ratio, not shallow"
    assert "deep_read" in names, "high Read:Edit should be detected as deep_read"


# ─── Low Diversity ────────────────────────────────────────────────────────────

def test_low_diversity_detected():
    msgs = [
        {"role": "user", "content": "refactor the code"},
        {"role": "assistant", "content": "", "tool_calls": [
            {"function": {"name": "read_file"}}]},
        {"role": "user", "content": "continue"},
        {"role": "assistant", "content": "", "tool_calls": [
            {"function": {"name": "read_file"}}]},
        {"role": "user", "content": "more"},
        {"role": "assistant", "content": "", "tool_calls": [
            {"function": {"name": "read_file"}}]},
        {"role": "user", "content": "more"},
        {"role": "assistant", "content": "", "tool_calls": [
            {"function": {"name": "read_file"}}]},
        {"role": "user", "content": "more"},
        {"role": "assistant", "content": "", "tool_calls": [
            {"function": {"name": "read_file"}}]},
    ]
    result = extract_signals(msgs, "coding")
    names = [s.name for s in result.signals]
    assert "low_diversity" in names


# ─── Weights and Feedback ─────────────────────────────────────────────────────

def test_weight_feedback_in_pipeline():
    """Placeholder: weights module comes in a later unit."""
    # Weights will be tested in test_weights.py once implemented
