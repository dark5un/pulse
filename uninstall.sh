#!/usr/bin/env bash
set -euo pipefail

# Pulse — Hermes session health monitor
# Uninstaller: removes plugin, keeps repo

echo "==> Uninstalling Pulse..."

# Remove plugin symlink and yaml
PLUGIN_DIR="${HOME}/.hermes/plugins/pulse"
if [ -d "$PLUGIN_DIR" ]; then
    rm -f "$PLUGIN_DIR/__init__.py"
    rm -f "$PLUGIN_DIR/plugin.yaml"
    rmdir "$PLUGIN_DIR" 2>/dev/null || true
    echo "  Removed plugin from $PLUGIN_DIR"
fi

# Remove pulse_results table from state.db (optional)
if [ -f "${HOME}/.hermes/state.db" ]; then
    echo "  Pulse data still in state.db (pulse_results table)."
    echo "  To remove it: sqlite3 ~/.hermes/state.db 'DROP TABLE IF EXISTS pulse_results;'"
fi

# Remove weights file
if [ -f "${HOME}/.hermes/pulse_weights.json" ]; then
    rm -f "${HOME}/.hermes/pulse_weights.json"
    echo "  Removed pulse weights file"
fi

echo ""
echo "==> Pulse uninstalled."
echo "  Repo kept at ~/workspace/github.com/dark5un/pulse — remove manually if desired."
echo "  Restart Hermes to complete."