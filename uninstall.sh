#!/usr/bin/env bash
set -euo pipefail
HERMES_HOME_DIR="${HERMES_HOME:-${HOME}/.hermes}"
PLUGIN_DIR="$HERMES_HOME_DIR/plugins/pulse"
if command -v hermes >/dev/null 2>&1; then hermes plugins disable pulse >/dev/null 2>&1 || true; fi
# Remove everything install.sh may have placed (flat modules + legacy nested copy).
rm -f "$PLUGIN_DIR/__init__.py" "$PLUGIN_DIR/plugin.yaml"
rm -f "$PLUGIN_DIR/"*.py
rm -rf "$PLUGIN_DIR/pulse" "$PLUGIN_DIR/__pycache__"
rmdir "$PLUGIN_DIR" 2>/dev/null || true
rm -f "$HERMES_HOME_DIR/pulse_weights.json"
printf 'Pulse plugin removed from %s (analysis data in state.db retained).\n' "$HERMES_HOME_DIR"
