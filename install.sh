#!/usr/bin/env bash
set -euo pipefail

# Install from git, or from PULSE_SOURCE_DIR for offline/release smoke tests.
REPO_URL="https://github.com/dark5un/pulse.git"
INSTALL_DIR="${PULSE_INSTALL_DIR:-${HOME}/workspace/github.com/dark5un/pulse}"
HERMES_HOME_DIR="${HERMES_HOME:-${HOME}/.hermes}"
SOURCE_DIR="${PULSE_SOURCE_DIR:-}"

if [[ -n "$SOURCE_DIR" ]]; then
  [[ -f "$SOURCE_DIR/src/pulse/plugin.yaml" ]] || { echo "Missing src/pulse/plugin.yaml in $SOURCE_DIR" >&2; exit 1; }
  [[ -f "$SOURCE_DIR/src/pulse/plugin.py" ]] || { echo "Missing src/pulse/plugin.py in $SOURCE_DIR" >&2; exit 1; }
  INSTALL_DIR="$SOURCE_DIR"
elif [[ -d "$INSTALL_DIR/.git" ]]; then
  git -C "$INSTALL_DIR" pull --ff-only
else
  mkdir -p "$(dirname "$INSTALL_DIR")"
  git clone "$REPO_URL" "$INSTALL_DIR"
fi

PLUGIN_DIR="$HERMES_HOME_DIR/plugins/pulse"
mkdir -p "$PLUGIN_DIR"
cp "$INSTALL_DIR/src/pulse/plugin.yaml" "$PLUGIN_DIR/plugin.yaml"
ln -sfn "$INSTALL_DIR/src/pulse/plugin.py" "$PLUGIN_DIR/__init__.py"
# Keep the package imports self-contained when Hermes loads this directory.
mkdir -p "$PLUGIN_DIR/pulse"
cp "$INSTALL_DIR/src/pulse"/*.py "$PLUGIN_DIR/pulse/"
if command -v hermes >/dev/null 2>&1; then hermes plugins enable pulse; fi
printf 'Pulse installed at %s\n' "$PLUGIN_DIR"
