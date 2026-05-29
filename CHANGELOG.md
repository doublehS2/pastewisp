# Changelog

All notable changes to Pastewisp are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.0] - 2026-05-30

First public release. Targets Ubuntu (GNOME, X11) with GTK 4.

### Added
- Clipboard text history with SQLite FTS5 search (handles CJK substrings).
- Global hotkey popup (default `Ctrl+Shift+V`), opening at the mouse cursor.
- Keyboard-first flow: live filter, arrow navigation, `Enter` to copy +
  auto-paste (XTest) into the previously focused window, `Shift+Enter` to copy
  only.
- Position shortcuts (`Ctrl+1..9, Ctrl+0`) and fixed alphabet shortcuts for
  pinned items (`Ctrl+A..Z`).
- Pinning / favorites with an Alt-mode pin-toggle overlay.
- Image clipboard history with thumbnails and configurable retention.
- App exclusion (password managers excluded by default).
- Delete individual entries; clear all history (with confirmation, keeps pinned).
- Preferences window: hotkey, history size, auto-paste, image retention,
  language (auto/en/ko), excluded apps.
- System tray menu via an AyatanaAppIndicator subprocess.
- systemd user service for autostart on login.
- Refined dark UI.
- `.deb` package and install/uninstall scripts.

### Known limitations
- Wayland is not supported (XGrabKey and XTest are X11-only).
- GNOME does not show AppIndicator/SNI tray icons without the
  "AppIndicator and KStatusNotifierItem Support" extension.
- Auto-paste can be blocked by sandboxed apps; use `Shift+Enter` to copy only.

[Unreleased]: https://github.com/doublehS2/pastewisp/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/doublehS2/pastewisp/releases/tag/v0.1.0
