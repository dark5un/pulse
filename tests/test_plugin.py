"""Tests for the Hermes Pulse plugin.

Tests that the /pulse slash command handler renders correctly
without needing a live Hermes session or state.db.
"""

import sys
from pathlib import Path

# Add plugin dir to path
plugin_dir = Path.home() / ".hermes" / "plugins" / "pulse"
sys.path.insert(0, str(plugin_dir))

# Add pulse project src to path
pulse_src = Path.home() / "workspace" / "pulse" / "src"
sys.path.insert(0, str(pulse_src))

# Import the plugin module — this is what we're testing
import importlib

from pulse.models import Signal, SignalResult
from pulse.signals import extract_signals

plugin = importlib.import_module("__init__")


# ─── _render_card tests ──────────────────────────────────────────────────

def test_render_card_green():
    """Sessions with no signals should show GREEN status."""
    metrics = {
        "total_turns": 42, "total_tokens": 12000, "tool_call_count": 15,
        "read_edit_ratio": 3.5, "user_turns": 8, "agent_turns": 8,
        "reads": 10, "edits": 3, "tool_names": ["read_file", "write_file"],
        "task_type": "coding", "user_texts": [], "agent_texts": [],
    }
    result = SignalResult(signals=[], metrics=metrics)
    card = plugin._render_card(result, "coding")
    assert "Pulse" in card
    assert "GREEN" in card
    assert "42" in card
    assert "12,000" in card
    assert "Session looks productive" in card


def test_render_card_red():
    """Sessions with high penalty should show RED status."""
    metrics = {
        "total_turns": 20, "total_tokens": 5000, "tool_call_count": 10,
        "read_edit_ratio": 0.5, "user_turns": 5, "agent_turns": 5,
        "reads": 1, "edits": 2, "tool_names": ["write_file"],
        "task_type": "coding", "user_texts": [], "agent_texts": [],
    }
    signals = [
        Signal(name="correction_chain", target="user", severity="warning",
               penalty=20, evidence=["no, that's wrong", "no, still not"]),
        Signal(name="tool_error", target="agent", severity="warning",
               penalty=15, evidence=["Error: connection refused"]),
        Signal(name="tool_error", target="agent", severity="warning",
               penalty=15, evidence=["Error: timeout"]),
    ]
    result = SignalResult(signals=signals, metrics=metrics)
    card = plugin._render_card(result, "coding")
    assert "RED" in card
    assert "Significant problems found" in card
    assert "correction_chain" in card or "YOU" in card
    assert "tool_error" in card or "AGT" in card


def test_render_card_coaching_appears():
    """Coaching tips should appear when signals are present."""
    metrics = {
        "total_turns": 20, "total_tokens": 5000, "tool_call_count": 10,
        "read_edit_ratio": 0.5, "user_turns": 5, "agent_turns": 5,
        "reads": 1, "edits": 2, "tool_names": ["write_file"],
        "task_type": "coding", "user_texts": [], "agent_texts": [],
    }
    signals = [
        Signal(name="correction_chain", target="user", severity="warning", penalty=12, evidence=[]),
        Signal(name="tool_error", target="agent", severity="warning", penalty=8, evidence=[]),
    ]
    result = SignalResult(signals=signals, metrics=metrics)
    card = plugin._render_card(result, "coding")
    assert "Coaching" in card
    assert "instead of 'no'" in card
    assert "different approach" in card


def test_render_card_no_coaching_when_clean():
    """Clean sessions should show green status but no coaching section."""
    metrics = {
        "total_turns": 10, "total_tokens": 1000, "tool_call_count": 5,
        "read_edit_ratio": 4.0, "user_turns": 3, "agent_turns": 3,
        "reads": 4, "edits": 1, "tool_names": ["read_file", "write_file"],
        "task_type": "coding", "user_texts": [], "agent_texts": [],
    }
    result = SignalResult(signals=[], metrics=metrics)
    card = plugin._render_card(result, "coding")
    assert "GREEN" in card
    assert "Session looks productive" in card
    assert "Coaching" not in card


def test_render_card_shows_evidence():
    """Signals with evidence should show the evidence text."""
    metrics = {
        "total_turns": 30, "total_tokens": 8000, "tool_call_count": 20,
        "read_edit_ratio": 1.0, "user_turns": 8, "agent_turns": 8,
        "reads": 5, "edits": 5, "tool_names": ["read_file", "write_file"],
        "task_type": "coding", "user_texts": [], "agent_texts": [],
    }
    signals = [
        Signal(name="frustration", target="user", severity="warning",
               penalty=12, evidence=["you're so lazy, do it properly"]),
    ]
    result = SignalResult(signals=signals, metrics=metrics)
    card = plugin._render_card(result, "coding")
    assert "lazy" in card


# ─── _handle_pulse tests ─────────────────────────────────────────────────

def test_handle_pulse_no_session():
    """Without a session, handle_pulse should return error message."""
    # When no state.db or session exists, it should return a message
    result = plugin._handle_pulse("")
    assert isinstance(result, str)
    assert len(result) > 0


def test_handle_pulse_returns_string():
    """handle_pulse should always return a string."""
    result = plugin._handle_pulse("--json")
    assert isinstance(result, str)


# ─── register(ctx) tests ─────────────────────────────────────────────────

def test_register_calls_register_command():
    """register() should call ctx.register_command with 'pulse'."""
    registered = {}

    class FakeCtx:
        def register_command(self, name, handler, description, args_hint=""):
            registered["name"] = name
            registered["handler"] = handler
            registered["description"] = description
            registered["args_hint"] = args_hint

    plugin.register(FakeCtx())
    assert registered["name"] == "pulse"
    assert registered["handler"] is not None
    assert "session" in registered["description"].lower()
    # Verify handler returns a string when called
    result = registered["handler"]("")
    assert isinstance(result, str)


# ─── Integration: extract_signals round-trip ─────────────────────────────

def test_pulse_imports_work():
    """The pulse project imports should resolve correctly."""
    from pulse.models import Signal, SignalResult
    assert extract_signals is not None
    assert Signal is not None
    assert SignalResult is not None