#!/usr/bin/env bash
# Pastewisp uninstaller.
# Default: disable + stop the service only (keeps config and DB).
# --purge: also remove venv, config, and DB.

set -euo pipefail

PURGE=0
if [ "${1:-}" = "--purge" ]; then
  PURGE=1
fi

UNIT_PATH="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user/pastewisp.service"
VENV_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/pastewisp/venv"
DATA_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/pastewisp"
CONFIG_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/pastewisp"
DESKTOP_FILE="${XDG_DATA_HOME:-$HOME/.local/share}/applications/pastewisp.desktop"

echo "==> Stopping pastewisp.service"
systemctl --user disable --now pastewisp.service 2>/dev/null || true
rm -f "$UNIT_PATH"
systemctl --user daemon-reload
rm -f "$DESKTOP_FILE"

if [ $PURGE -eq 1 ]; then
  echo "==> --purge: removing venv, data, and config"
  rm -rf "$VENV_DIR" "$DATA_DIR" "$CONFIG_DIR"
else
  echo "    Config and DB preserved ($CONFIG_DIR, $DATA_DIR)"
  echo "    Full removal: $0 --purge"
fi

echo "✓ Uninstall complete"
