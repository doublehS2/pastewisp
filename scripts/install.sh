#!/usr/bin/env bash
# Pastewisp installer.
# - Checks APT dependencies.
# - Creates $XDG_DATA_HOME/pastewisp/venv (--system-site-packages so PyGObject
#   is shared from the system instead of being rebuilt).
# - Installs the package in editable mode.
# - Registers and starts a systemd --user unit.

set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
VENV_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/pastewisp/venv"
UNIT_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
UNIT_PATH="$UNIT_DIR/pastewisp.service"

cyan()  { printf "\033[36m%s\033[0m\n" "$*"; }
red()   { printf "\033[31m%s\033[0m\n" "$*"; }
green() { printf "\033[32m%s\033[0m\n" "$*"; }

cyan "==> Installing Pastewisp"
cyan "    repo: $REPO_DIR"
cyan "    venv: $VENV_DIR"
cyan "    unit: $UNIT_PATH"

# ─── 1. APT dependency check ───
REQ_PACKAGES=(
  python3-venv
  python3-gi
  gir1.2-gtk-4.0
  gir1.2-gtk-3.0
  gir1.2-ayatanaappindicator3-0.1
  gir1.2-atspi-2.0
  xclip
)
MISSING=()
for pkg in "${REQ_PACKAGES[@]}"; do
  if ! dpkg -s "$pkg" >/dev/null 2>&1; then
    MISSING+=("$pkg")
  fi
done
if [ ${#MISSING[@]} -gt 0 ]; then
  red "Missing system packages:"
  printf "  - %s\n" "${MISSING[@]}"
  echo
  echo "Install them with:"
  echo "  sudo apt install ${MISSING[*]}"
  exit 1
fi
green "[ok] APT dependencies satisfied"

# ─── 2. venv ───
mkdir -p "$(dirname "$VENV_DIR")"
if [ ! -d "$VENV_DIR" ]; then
  cyan "==> Creating venv ($VENV_DIR)"
  python3 -m venv --system-site-packages "$VENV_DIR"
fi
"$VENV_DIR/bin/pip" install --quiet --upgrade pip
cyan "==> Installing package (editable)"
"$VENV_DIR/bin/pip" install --quiet -e "$REPO_DIR"

# ─── 3. systemd unit ───
mkdir -p "$UNIT_DIR"
sed "s#@PYTHON@#$VENV_DIR/bin/python#g" "$REPO_DIR/data/pastewisp.service.in" > "$UNIT_PATH"
cyan "==> Registering systemd user unit"
systemctl --user daemon-reload
systemctl --user enable --now pastewisp.service
sleep 1
if systemctl --user is-active --quiet pastewisp.service; then
  green "[ok] pastewisp.service active"
else
  red "[!] pastewisp.service is not active. Check the logs with:"
  echo "    journalctl --user -u pastewisp.service -n 50"
  exit 1
fi

# ─── 4. .desktop ───
APPS_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
mkdir -p "$APPS_DIR"
cp "$REPO_DIR/data/pastewisp.desktop" "$APPS_DIR/pastewisp.desktop"

# ─── 5. Self-check ───
"$VENV_DIR/bin/python" -m pastewisp --self-check || true

green ""
green "✓ Install complete. Default hotkey: Ctrl+Shift+V"
green "  Config file: ${XDG_CONFIG_HOME:-$HOME/.config}/pastewisp/config.toml"
green "  Status:      systemctl --user status pastewisp"
green "  Tail logs:   journalctl --user -u pastewisp -f"
