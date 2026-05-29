#!/usr/bin/env bash
# Record a Pastewisp demo GIF on an X11 GNOME desktop.
#
# Strategy:
#   - Stop the live service (avoids a double Ctrl+Shift+V grab) and use an
#     ISOLATED XDG_DATA_HOME / XDG_CONFIG_HOME with a seeded demo DB, so the
#     real clipboard history is never shown.
#   - Open gnome-text-editor as the paste target, place it at a fixed rect.
#   - Drive copy -> hotkey -> search -> select -> auto-paste with xdotool.
#   - Capture a screen region with ffmpeg x11grab, convert to an optimized GIF.
#
# Output: docs/demo.gif  (+ docs/_demo.mp4 raw capture, docs/_demo_frame.png)
#
# Note: deliberately NOT using `set -e` — xdotool/wmctrl emit harmless
# non-zero/stderr on this GNOME/X11 setup, and we want the run to push through
# to the recording rather than abort on a cosmetic failure.
set -uo pipefail

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
export DISPLAY="${DISPLAY:-:1}"

PY="$REPO_DIR/.venv/bin/python"
DEMO_HOME="$(mktemp -d /tmp/pastewisp-demo.XXXXXX)"
export XDG_DATA_HOME="$DEMO_HOME/data"
export XDG_CONFIG_HOME="$DEMO_HOME/config"
export XDG_CACHE_HOME="$DEMO_HOME/cache"
mkdir -p "$XDG_DATA_HOME" "$XDG_CONFIG_HOME" "$XDG_CACHE_HOME"

# Capture geometry. The editor is MAXIMIZED to fill its monitor (the portrait
# monitor at x=0, 1440 wide), so the record region — centred well inside it —
# can never leak the desktop behind. Popup (580x500) is warped inside too.
REC_X=0; REC_Y=90; REC_W=1320; REC_H=1010
WARP_X=380; WARP_Y=360
# screenkey overlay bar — drawn inside the bottom of the capture region so the
# keys being pressed (hotkey, search query, Enter) are visible in the GIF.
SK_GEO="1180x74+90+980"
OUT_MP4="$REPO_DIR/docs/_demo.mp4"
OUT_GIF="$REPO_DIR/docs/demo.gif"

SERVICE_WAS_ACTIVE=0
EDITOR_PID=""
APP_PID=""
FFMPEG_PID=""
SK_PID=""

cleanup() {
  set +e
  [ -n "$FFMPEG_PID" ] && kill "$FFMPEG_PID" 2>/dev/null
  [ -n "$SK_PID" ] && kill "$SK_PID" 2>/dev/null
  [ -n "$APP_PID" ] && kill "$APP_PID" 2>/dev/null
  [ -n "$EDITOR_PID" ] && kill "$EDITOR_PID" 2>/dev/null
  # restore the user's service
  if [ "$SERVICE_WAS_ACTIVE" = "1" ]; then
    systemctl --user start pastewisp 2>/dev/null
  fi
  # restore the editor's session-restore preference
  if [ -n "${PREV_RESTORE:-}" ]; then
    gsettings set org.gnome.TextEditor restore-session "$PREV_RESTORE" 2>/dev/null
  fi
  rm -rf "$DEMO_HOME"
}
trap cleanup EXIT

echo "==> demo XDG home: $DEMO_HOME"

# 0. Stop the live service so it doesn't also grab the hotkey.
if systemctl --user is-active --quiet pastewisp; then
  SERVICE_WAS_ACTIVE=1
  echo "==> stopping live pastewisp service"
  systemctl --user stop pastewisp
  sleep 1
fi

# 1. Seed demo history.
echo "==> seeding demo DB"
"$PY" "$REPO_DIR/scripts/_seed_demo.py"

# 2. Write a demo config (auto-paste on, English UI).
mkdir -p "$XDG_CONFIG_HOME/pastewisp"
cat > "$XDG_CONFIG_HOME/pastewisp/config.toml" <<'TOML'
[general]
history_limit = 500
hotkey = "<Control><Shift>v"
auto_paste = true
start_minimized_to_tray = true
language = "en"
TOML

# 3. Launch the editor (paste target) on a clean empty file, then place it.
# Disable session restore so only the demo file is shown (no leftover tabs).
PREV_RESTORE="$(gsettings get org.gnome.TextEditor restore-session 2>/dev/null || true)"
gsettings set org.gnome.TextEditor restore-session false 2>/dev/null || true
pkill -x gnome-text-editor 2>/dev/null || true
sleep 1
DEMO_TXT="$DEMO_HOME/scratch.txt"
: > "$DEMO_TXT"
setsid gnome-text-editor "$DEMO_TXT" >/dev/null 2>&1 < /dev/null &
# Poll for the editor window (single-instance app, so match by class).
ED_WIN=""
for _ in $(seq 1 30); do
  # Match the real document window by title (avoids the 1x1 helper window
  # that gnome-text-editor's GtkApplication also creates).
  ED_WIN="$(xdotool search --name "scratch.txt" 2>/dev/null | tail -1)"
  if [ -n "$ED_WIN" ]; then
    # sanity: skip if it's a 1x1 window
    geo="$(xdotool getwindowgeometry "$ED_WIN" 2>/dev/null | grep Geometry || true)"
    case "$geo" in *"1x1"*) ED_WIN="";; esac
  fi
  [ -n "$ED_WIN" ] && break
  sleep 0.3
done
if [ -z "$ED_WIN" ]; then
  echo "!! could not find gnome-text-editor window" >&2
  exit 1
fi
xdotool windowactivate "$ED_WIN" 2>/dev/null || true
# Pin it to the portrait monitor at x=0, then maximize so it fills the screen.
xdotool windowmove "$ED_WIN" 0 0 2>/dev/null || true
sleep 0.4
wmctrl -i -r "$ED_WIN" -b add,maximized_vert,maximized_horz 2>/dev/null || true
sleep 0.4
xdotool windowraise "$ED_WIN" 2>/dev/null || true
xdotool windowactivate "$ED_WIN" 2>/dev/null || true
EDITOR_PID="$(xdotool getwindowpid "$ED_WIN" 2>/dev/null || true)"
xdotool getwindowgeometry "$ED_WIN" 2>/dev/null || true
sleep 0.6
xdotool type --delay 35 "# Pastewisp demo — search your clipboard history, hit Enter, paste:"
xdotool key Return
xdotool key Return
sleep 0.6

# 4. Launch the isolated Pastewisp instance (grabs the hotkey).
echo "==> launching demo pastewisp"
"$PY" -m pastewisp >"$DEMO_HOME/app.log" 2>&1 &
APP_PID=$!
sleep 4

# 5. Start the keystroke overlay (screenkey), then record.
echo "==> starting screenkey overlay"
screenkey --no-systray -p fixed -g "$SK_GEO" \
  -s large --timeout 1.6 --key-mode composed --mods-mode emacs \
  --bg-color "#11121a" --font-color "#e6e6f0" --opacity 0.95 \
  >/dev/null 2>&1 &
SK_PID=$!
sleep 1.5

echo "==> recording"
ffmpeg -y -hide_banner -loglevel error \
  -f x11grab -framerate 20 -video_size "${REC_W}x${REC_H}" \
  -i "${DISPLAY}+${REC_X},${REC_Y}" \
  -t 18 "$OUT_MP4" &
FFMPEG_PID=$!
sleep 1.2

# Helper: warp pointer into the capture region so the popup appears there.
warp() { xdotool mousemove "$1" "$2"; }

demo_paste() {
  local query="$1"
  # ensure editor is the previously-focused window
  [ -n "$ED_WIN" ] && xdotool windowactivate "$ED_WIN"
  sleep 0.4
  warp "$WARP_X" "$WARP_Y"
  xdotool key ctrl+shift+v
  sleep 1.2
  xdotool type --delay 90 "$query"
  sleep 1.3
  xdotool key Return
  sleep 1.4
}

# 6. The demo sequence.
demo_paste "git"
xdotool key Return
demo_paste "example"
xdotool key Return
demo_paste "fox"

# Let the recording finish.
wait "$FFMPEG_PID" 2>/dev/null || true
FFMPEG_PID=""
echo "==> capture done: $OUT_MP4"

# 7. Convert to an optimized, looping GIF (two-pass palette).
echo "==> converting to GIF"
PALETTE="$DEMO_HOME/palette.png"
GIF_FPS=12
GIF_W=760
ffmpeg -y -hide_banner -loglevel error -i "$OUT_MP4" \
  -vf "fps=${GIF_FPS},scale=${GIF_W}:-1:flags=lanczos,palettegen=stats_mode=diff" "$PALETTE"
ffmpeg -y -hide_banner -loglevel error -i "$OUT_MP4" -i "$PALETTE" \
  -lavfi "fps=${GIF_FPS},scale=${GIF_W}:-1:flags=lanczos[x];[x][1:v]paletteuse=dither=bayer:bayer_scale=3" \
  -loop 0 "$OUT_GIF"

# 8. Dump a mid frame for visual verification.
ffmpeg -y -hide_banner -loglevel error -ss 8 -i "$OUT_MP4" -frames:v 1 "$REPO_DIR/docs/_demo_frame.png" || true

ls -lh "$OUT_GIF"
echo "==> done"
