#!/usr/bin/env bash
# Build a Debian/Ubuntu .deb for Pastewisp.
#
# Pure-Python (Architecture: all). PyGObject and the other GTK/X11 bindings are
# pulled in as system dependencies rather than bundled, matching how the app is
# meant to run on Ubuntu/GNOME.
#
# Output: dist/pastewisp_<version>_all.deb
set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_DIR"

VERSION="$(sed -n 's/^version = "\(.*\)"/\1/p' pyproject.toml | head -1)"
[ -n "$VERSION" ] || { echo "could not read version from pyproject.toml" >&2; exit 1; }
PKG="pastewisp"
ARCH="all"
STAGE="$(mktemp -d /tmp/${PKG}-deb.XXXXXX)"
OUT_DIR="$REPO_DIR/dist"
DEB="$OUT_DIR/${PKG}_${VERSION}_${ARCH}.deb"

echo "==> building $PKG $VERSION ($ARCH)"
mkdir -p "$OUT_DIR"

# ─── layout ───
SITE="$STAGE/usr/lib/python3/dist-packages"
mkdir -p "$SITE" \
         "$STAGE/usr/bin" \
         "$STAGE/usr/share/applications" \
         "$STAGE/usr/share/icons/hicolor/scalable/apps" \
         "$STAGE/usr/lib/systemd/user" \
         "$STAGE/usr/share/doc/$PKG" \
         "$STAGE/DEBIAN"

# 1. Python package (strip caches / build metadata).
cp -r "$REPO_DIR/src/pastewisp" "$SITE/pastewisp"
find "$SITE/pastewisp" -type d -name '__pycache__' -prune -exec rm -rf {} +
rm -rf "$SITE/pastewisp.egg-info" 2>/dev/null || true

# 2. Launcher.
cat > "$STAGE/usr/bin/pastewisp" <<'SH'
#!/bin/sh
exec /usr/bin/python3 -m pastewisp "$@"
SH
chmod 0755 "$STAGE/usr/bin/pastewisp"

# 3. Desktop entry (point Icon at our shipped svg).
sed 's/^Icon=.*/Icon=pastewisp/' "$REPO_DIR/data/pastewisp.desktop" \
  > "$STAGE/usr/share/applications/pastewisp.desktop"

# 4. Icon.
cp "$REPO_DIR/data/icons/pastewisp.svg" \
   "$STAGE/usr/share/icons/hicolor/scalable/apps/pastewisp.svg"

# 5. systemd user unit (system python).
sed 's#@PYTHON@#/usr/bin/python3#g' "$REPO_DIR/data/pastewisp.service.in" \
  > "$STAGE/usr/lib/systemd/user/pastewisp.service"

# 6. Docs.
cp "$REPO_DIR/README.md" "$STAGE/usr/share/doc/$PKG/README.md"
[ -f "$REPO_DIR/CHANGELOG.md" ] && cp "$REPO_DIR/CHANGELOG.md" "$STAGE/usr/share/doc/$PKG/changelog.md"

# ─── control ───
INSTALLED_KB="$(du -sk "$STAGE/usr" | cut -f1)"
cat > "$STAGE/DEBIAN/control" <<EOF
Package: $PKG
Version: $VERSION
Architecture: $ARCH
Maintainer: doublehS2 <doublehS2@users.noreply.github.com>
Section: utils
Priority: optional
Installed-Size: $INSTALLED_KB
Depends: python3 (>= 3.11), python3-gi, gir1.2-gtk-4.0, gir1.2-gtk-3.0, gir1.2-ayatanaappindicator3-0.1, gir1.2-atspi-2.0, python3-xlib, python3-pil, python3-tomli-w, xclip
Homepage: https://github.com/doublehS2/pastewisp
Description: Fast, minimal clipboard history manager for Linux
 Pastewisp is a fast, minimal, keyboard-first clipboard history manager for
 Linux desktops (first target: Ubuntu/GNOME on X11). Press a global hotkey,
 search your clipboard history, hit Enter, and paste back into the focused
 window. History is stored locally; nothing is uploaded.
EOF

# postinst: refresh caches and tell the user how to autostart (per-user service).
cat > "$STAGE/DEBIAN/postinst" <<'SH'
#!/bin/sh
set -e
if [ "$1" = "configure" ]; then
  if command -v gtk-update-icon-cache >/dev/null 2>&1; then
    gtk-update-icon-cache -q -t /usr/share/icons/hicolor 2>/dev/null || true
  fi
  if command -v update-desktop-database >/dev/null 2>&1; then
    update-desktop-database -q /usr/share/applications 2>/dev/null || true
  fi
  echo "Pastewisp installed. To enable autostart for your user, run:"
  echo "    systemctl --user enable --now pastewisp"
  echo "Default popup hotkey: Ctrl+Shift+V  (X11 session required)"
fi
exit 0
SH
chmod 0755 "$STAGE/DEBIAN/postinst"

# ─── build ───
dpkg-deb --root-owner-group --build "$STAGE" "$DEB"
rm -rf "$STAGE"

echo "==> built: $DEB"
dpkg-deb --info "$DEB"
echo "---- contents ----"
dpkg-deb --contents "$DEB"
