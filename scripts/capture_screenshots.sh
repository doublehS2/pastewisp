#!/usr/bin/env bash
# Regenerate the README screenshots cleanly — captures ONLY the Pastewisp popup
# window (over a maximized blank editor as a neutral dark backdrop), so no
# desktop / browser / bookmark bar ever appears.
#
# Outputs: docs/popup.png  docs/popup-empty.png  docs/popup-alt-mode.png
set -uo pipefail

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
export DISPLAY="${DISPLAY:-:1}"
PY="$REPO_DIR/.venv/bin/python"

DEMO_HOME="$(mktemp -d /tmp/pastewisp-shot.XXXXXX)"
export XDG_DATA_HOME="$DEMO_HOME/data"
export XDG_CONFIG_HOME="$DEMO_HOME/config"
export XDG_CACHE_HOME="$DEMO_HOME/cache"
mkdir -p "$XDG_DATA_HOME" "$XDG_CONFIG_HOME/pastewisp" "$XDG_CACHE_HOME"

WARP_X=380; WARP_Y=360
SERVICE_WAS_ACTIVE=0; EDITOR_PID=""; APP_PID=""; PREV_RESTORE=""

cleanup() {
  set +e
  [ -n "$APP_PID" ] && kill "$APP_PID" 2>/dev/null
  [ -n "$EDITOR_PID" ] && kill "$EDITOR_PID" 2>/dev/null
  pkill -x screenkey 2>/dev/null
  [ "$SERVICE_WAS_ACTIVE" = "1" ] && systemctl --user start pastewisp 2>/dev/null
  [ -n "$PREV_RESTORE" ] && gsettings set org.gnome.TextEditor restore-session "$PREV_RESTORE" 2>/dev/null
  rm -rf "$DEMO_HOME"
}
trap cleanup EXIT

cat > "$XDG_CONFIG_HOME/pastewisp/config.toml" <<'TOML'
[general]
history_limit = 500
hotkey = "<Control><Shift>v"
auto_paste = true
start_minimized_to_tray = true
language = "en"
TOML

if systemctl --user is-active --quiet pastewisp; then
  SERVICE_WAS_ACTIVE=1; systemctl --user stop pastewisp; sleep 1
fi

# Blank maximized editor as a neutral dark backdrop (covers the desktop).
PREV_RESTORE="$(gsettings get org.gnome.TextEditor restore-session 2>/dev/null || true)"
gsettings set org.gnome.TextEditor restore-session false 2>/dev/null || true
pkill -x gnome-text-editor 2>/dev/null || true
sleep 1
: > "$DEMO_HOME/scratch.txt"
setsid gnome-text-editor "$DEMO_HOME/scratch.txt" >/dev/null 2>&1 < /dev/null &
ED_WIN=""
for _ in $(seq 1 30); do
  ED_WIN="$(xdotool search --name "scratch.txt" 2>/dev/null | tail -1)"
  [ -n "$ED_WIN" ] && break; sleep 0.3
done
[ -n "$ED_WIN" ] && {
  xdotool windowactivate "$ED_WIN" 2>/dev/null
  xdotool windowmove "$ED_WIN" 0 0 2>/dev/null
  EDITOR_PID="$(xdotool getwindowpid "$ED_WIN" 2>/dev/null || true)"
  wmctrl -i -r "$ED_WIN" -b add,maximized_vert,maximized_horz 2>/dev/null
}
sleep 1

# ── find the popup window (title "Pastewisp", real size, not the 1x1 helper) ──
find_popup() {
  local id geo w
  for id in $(xdotool search --name "^Pastewisp$" 2>/dev/null); do
    geo="$(xdotool getwindowgeometry "$id" 2>/dev/null)"
    w="$(printf '%s\n' "$geo" | sed -n 's/.*Geometry: \([0-9]*\)x.*/\1/p')"
    if [ -n "$w" ] && [ "$w" -ge 400 ] && [ "$w" -le 900 ]; then echo "$id"; return; fi
  done
}

# ── capture the popup window region from root (so transparent corners show the
#    dark editor behind, not the desktop) ──
shoot() {
  local out="$1"
  local pid geo x y w h
  pid="$(find_popup)"
  if [ -z "$pid" ]; then echo "!! popup window not found for $out" >&2; return 1; fi
  geo="$(xdotool getwindowgeometry --shell "$pid")"
  eval "$geo"   # sets X Y WIDTH HEIGHT
  # small negative pad to trim the transparent CSD shadow margin
  local pad=8
  x=$(( X + pad )); y=$(( Y + pad )); w=$(( WIDTH - pad*2 )); h=$(( HEIGHT - pad*2 ))
  import -window root -crop "${w}x${h}+${x}+${y}" +repage "$out"
  echo "==> $out  (${w}x${h} at ${x},${y})"
}

open_popup() { xdotool mousemove "$WARP_X" "$WARP_Y"; xdotool key ctrl+shift+v; sleep 1.2; }
close_popup() { xdotool key Escape; sleep 0.5; }

# ===== 1) normal + 2) alt-mode  (seeded history, incl. one image item) =====
PASTEWISP_SEED_IMAGE=1 "$PY" "$REPO_DIR/scripts/_seed_demo.py" >/dev/null
# Neutralize the clipboard so the watcher doesn't inject a stray item on startup
# (whitespace-only values are ignored), keeping the seeded list deterministic.
printf ' ' | xclip -selection clipboard -i 2>/dev/null || true
sleep 0.5
setsid "$PY" -m pastewisp >"$DEMO_HOME/app.log" 2>&1 < /dev/null &
APP_PID=$!
sleep 4

open_popup
shoot "$REPO_DIR/docs/popup.png"

# alt-mode: hold Alt so badges switch to pin-toggle mode
xdotool keydown alt; sleep 0.8
shoot "$REPO_DIR/docs/popup-alt-mode.png"
xdotool keyup alt; sleep 0.3
close_popup

# stop this instance before wiping the DB
kill "$APP_PID" 2>/dev/null; APP_PID=""; sleep 1.5

# ===== 3) empty state (wipe DB, fresh instance) =====
rm -f "$XDG_DATA_HOME/pastewisp/db.sqlite"*
# Neutralize the clipboard so the watcher captures nothing on startup
# (whitespace-only values are ignored by HistoryManager.add_text).
printf ' ' | xclip -selection clipboard -i 2>/dev/null || true
sleep 0.5
setsid "$PY" -m pastewisp >"$DEMO_HOME/app2.log" 2>&1 < /dev/null &
APP_PID=$!
sleep 4
open_popup
shoot "$REPO_DIR/docs/popup-empty.png"
close_popup

echo "==> done"
ls -lh "$REPO_DIR"/docs/popup*.png
