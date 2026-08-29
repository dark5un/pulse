"""Tests for the Pulse self-learning weights module."""

from pulse.weights import apply, get_feedback_count, load, record_feedback, save


def test_load_returns_defaults_when_no_file():
    """Loading weights when no file exists should return defaults."""
    weights = load()
    assert "correction_chain" in weights
    assert "reasoning_loop" in weights
    assert weights["correction_chain"]["penalty"] == 12


def test_save_and_load_roundtrip():
    """Save then load should return the same weights."""
    weights = {"test_signal": {"penalty": 10, "useful": 0, "not_useful": 0}, "_meta": {"total_feedback": 0}}
    save(weights)
    loaded = load()
    assert loaded["test_signal"]["penalty"] == 10


def test_apply_clamps_to_50_percent():
    """Apply should clamp penalty to ±50% of default."""
    weights = {"test_signal": {"penalty": 100, "useful": 0, "not_useful": 0}}
    result = apply(weights, "test_signal", 10)
    # ±50% of 10 = 5-15, so 100 should clamp to 15
    assert result == 15


def test_apply_uses_default_when_no_weight():
    """Apply should use default penalty when no weight exists."""
    weights = {}
    result = apply(weights, "nonexistent", 10)
    assert result == 10


def test_apply_normal_case():
    """Apply should return the learned weight when within range."""
    weights = {"my_signal": {"penalty": 8, "useful": 0, "not_useful": 0}}
    result = apply(weights, "my_signal", 10)
    assert result == 8


def test_cold_start_ignores_first_5_feedback():
    """First 5 feedback events should not change weights."""
    weights = {"test_sig": {"penalty": 10, "useful": 0, "not_useful": 0}}
    weights["_meta"] = {"total_feedback": 0}
    for _ in range(5):
        weights = record_feedback(weights, "test_sig", useful=False)
    assert weights["test_sig"]["penalty"] == 10, "Cold start should not change weights"


def test_feedback_increases_weight():
    """After cold start, useful feedback should increase weight if ratio > 0.7."""
    weights = {"test_sig": {"penalty": 10, "useful": 0, "not_useful": 0}}
    weights["_meta"] = {"total_feedback": 5}  # Past cold start
    # 3 useful, 0 not useful = 100% useful ratio
    for _ in range(3):
        weights = record_feedback(weights, "test_sig", useful=True)
    assert weights["test_sig"]["penalty"] > 10, "Useful feedback should increase weight"


def test_feedback_decreases_weight():
    """After cold start, not-useful feedback should decrease weight if ratio < 0.4."""
    weights = {"test_sig": {"penalty": 10, "useful": 0, "not_useful": 0}}
    weights["_meta"] = {"total_feedback": 5}  # Past cold start
    # 3 not useful, 0 useful = 0% useful ratio
    for _ in range(3):
        weights = record_feedback(weights, "test_sig", useful=False)
    assert weights["test_sig"]["penalty"] < 10, "Not-useful feedback should decrease weight"


def test_feedback_needs_minimum_3():
    """Feedback should not change weight until at least 3 events."""
    weights = {"test_sig": {"penalty": 10, "useful": 0, "not_useful": 0}}
    weights["_meta"] = {"total_feedback": 5}  # Past cold start
    weights = record_feedback(weights, "test_sig", useful=True)
    weights = record_feedback(weights, "test_sig", useful=True)
    # Only 2 events, needs 3 minimum
    assert weights["test_sig"]["penalty"] == 10, "Need 3+ events to change weight"


def test_get_feedback_count():
    """get_feedback_count should return the current count."""
    # Reset by loading
    _ = load()
    # Should be at least 0
    assert isinstance(get_feedback_count(), int)


def test_feedback_count_updates_in_same_process():
    weights = {"test_sig": {"penalty": 10, "useful": 0, "not_useful": 0},
               "_meta": {"total_feedback": 0}}
    load()
    record_feedback(weights, "test_sig", useful=True)
    assert get_feedback_count() == 1