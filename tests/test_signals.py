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
    """Output starting with 'Error:' should fire."""
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
    names = [s.name for s in result.signals]
    assert "tool_error" in names, "genuine error starting with 'Error:' should fire"


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
