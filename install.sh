#!/usr/bin/env bash
set -euo pipefail

# Pulse — Hermes session health monitor
# Installer: clones repo, sets up venv, links plugin

REPO_URL="https://github.com/dark5un/pulse.git"
INSTALL_DIR="${HOME}/workspace/github.com/dark5un/pulse"

echo "==> Installing Pulse..."

# Clone or pull
if [ -d "$INSTALL_DIR" ]; then
    echo "  Repo exists at $INSTALL_DIR, pulling latest..."
    git -C "$INSTALL_DIR" pull --ff-only
else
    echo "  Cloning to $INSTALL_DIR..."
    mkdir -p "$(dirname "$INSTALL_DIR")"
    git clone "$REPO_URL" "$INSTALL_DIR"
fi

# Install Python deps
echo "  Installing Python dependencies..."
cd "$INSTALL_DIR"
uv sync --extra dev 2>/dev/null || uv sync

# Create plugin directory
PLUGIN_DIR="${HOME}/.hermes/plugins/pulse"
mkdir -p "$PLUGIN_DIR"

# Copy plugin.yaml
cp src/pulse/plugin.yaml "$PLUGIN_DIR/"

# Create symlink to plugin.py
ln -sf "$INSTALL_DIR/src/pulse/plugin.py" "$PLUGIN_DIR/__init__.py"

echo "  Plugin linked to $PLUGIN_DIR"

# Enable in Hermes
if command -v hermes &>/dev/null; then
    echo "  Enabling plugin..."
    hermes plugins enable pulse 2>/dev/null || true
fi

echo ""
echo "==> Pulse installed!"
echo ""
echo "  Next steps:"
echo "    1. Restart Hermes (/exit then hermes)"
echo "    2. Type /pulse to analyze the current session"
echo "    3. Type /pulse trends to see historical data"
echo "    4. Type /pulse models to compare models"
echo ""