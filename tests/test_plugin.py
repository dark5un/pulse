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

# Shared test metrics
METRICS = {
    "total_turns": 42, "total_tokens": 12000, "tool_call_count": 15,
    "read_edit_ratio": 3.5, "user_turns": 8, "agent_turns": 8,
    "reads": 10, "edits": 3, "tool_names": ["read_file", "write_file"],
    "task_type": "coding", "user_texts": [], "agent_texts": [],
}


# ─── _render_card tests ──────────────────────────────────────────────────

def test_render_card_green():
    """Sessions with no signals should show GREEN status."""
    result = SignalResult(signals=[], metrics=METRICS)
    card = plugin._render_card(result, [], "coding")
    assert "Pulse" in card
    assert "GREEN" in card
    assert "42" in card


def test_render_card_red():
    """Sessions with high penalty should show RED status."""
    m = dict(METRICS)
    m["total_turns"] = 20
    m["total_tokens"] = 5000
    m["tool_call_count"] = 10
    signals_flat = [
        {"name": "correction_chain", "target": "user", "severity": "warning",
         "penalty": 20, "label": "3 consecutive correction turns",
         "evidence": ["no, that's wrong", "no, still not"]},
        {"name": "tool_error", "target": "agent", "severity": "warning",
         "penalty": 15, "label": "Tool returned an explicit error",
         "evidence": ["Error: connection refused"]},
        {"name": "tool_error", "target": "agent", "severity": "warning",
         "penalty": 15, "label": "Tool returned an explicit error",
         "evidence": ["Error: timeout"]},
    ]
    result = SignalResult(signals=[], metrics=m)
    card = plugin._render_card(result, signals_flat, "coding")
    assert "RED" in card
    assert "[-]" in card
    assert "correction" in card or "no, that's wrong" in card


def test_render_card_coaching_appears():
    """Coaching tips should appear when signals are present."""
    signals_flat = [
        {"name": "correction_chain", "target": "user", "severity": "warning",
         "penalty": 12, "label": "correction chain", "evidence": []},
        {"name": "tool_error", "target": "agent", "severity": "warning",
         "penalty": 8, "label": "tool error", "evidence": []},
    ]
    result = SignalResult(signals=[], metrics=METRICS)
    card = plugin._render_card(result, signals_flat, "coding")
    assert "Coaching" in card
    assert "use X approach" in card
    assert "different approach" in card


def test_render_card_no_coaching_when_clean():
    """Clean sessions should show green status but no coaching section."""
    result = SignalResult(signals=[], metrics=METRICS)
    card = plugin._render_card(result, [], "coding")
    assert "GREEN" in card
    assert "Coaching" not in card


def test_render_card_shows_evidence():
    """Signals with evidence should show the evidence text."""
    signals_flat = [
        {"name": "frustration", "target": "user", "severity": "warning",
         "penalty": 12, "label": "Frustration signals in 2 turns",
         "evidence": ["you're so lazy, do it properly"]},
    ]
    result = SignalResult(signals=[], metrics=METRICS)
    card = plugin._render_card(result, signals_flat, "coding")
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
    from pulse.models import SignalResult
    assert extract_signals is not None
    assert Signal is not None
    assert SignalResult is not None