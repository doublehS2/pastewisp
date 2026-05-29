# Contributing to Pastewisp

Thanks for your interest in improving Pastewisp! This is a small, focused
project — a fast, minimal clipboard history manager for Linux. Contributions
that keep it fast, simple, and honest about platform limitations are very
welcome.

## Ways to contribute

- **Report a bug** — open a [Bug report](https://github.com/doublehS2/pastewisp/issues/new?template=bug_report.yml).
- **Report desktop compatibility** — tried it on a distro/DE/session we haven't?
  Open a [Compatibility report](https://github.com/doublehS2/pastewisp/issues/new?template=compatibility_report.yml).
- **Request a feature** — open a [Feature request](https://github.com/doublehS2/pastewisp/issues/new?template=feature_request.yml).
  Please check the [Roadmap](README.md#roadmap) and the non-goals first; this
  project intentionally stays small.
- **Send a pull request** — see below.

## Local development setup

Pastewisp targets **Ubuntu (GNOME, X11)** with **GTK 4** via PyGObject. PyGObject
is shared from the system rather than rebuilt, so the venv is created with
`--system-site-packages`.

```bash
# 1. System dependencies (Debian/Ubuntu)
sudo apt install python3-venv python3-gi gir1.2-gtk-4.0 gir1.2-gtk-3.0 \
                 gir1.2-ayatanaappindicator3-0.1 gir1.2-atspi-2.0 xclip

# 2. Virtual environment + editable install
python3 -m venv --system-site-packages .venv
.venv/bin/pip install -e ".[dev]"

# 3. Run from source (foreground)
.venv/bin/python -m pastewisp
```

A real X11 session is required to exercise the hotkey, auto-paste, and popup
positioning code paths (`echo $XDG_SESSION_TYPE` must print `x11`). The unit
tests, however, are headless.

## Build instructions

To build the Debian package:

```bash
bash scripts/build_deb.sh        # → dist/pastewisp_<version>_all.deb
dpkg-deb --info  dist/pastewisp_*_all.deb
dpkg-deb --contents dist/pastewisp_*_all.deb
```

## Test instructions

```bash
.venv/bin/pytest                              # headless unit tests
.venv/bin/python -m pastewisp --self-check    # runtime diagnostics
.venv/bin/python scripts/smoke_watcher.py     # manual clipboard-watcher smoke test
```

All tests must pass before a PR is merged. CI runs `pytest` on every push and
pull request.

## Pull request checklist

- [ ] `.venv/bin/pytest` passes.
- [ ] New behavior has a test where it's reasonably testable.
- [ ] UI strings go through `i18n.t(...)` and exist in **both** the `EN` and
      `KO` catalogs (`src/pastewisp/i18n.py`) — `test_i18n.py` enforces parity.
- [ ] CSS tokens stay centralized in the `_CSS` block in `src/pastewisp/ui/popup.py`.
- [ ] Comments and user-facing strings (code side) are in English.
- [ ] The change keeps the app small and focused — no scope creep into the
      [non-goals](README.md#roadmap).

## Commit style

No strict convention is enforced. Short, imperative subject lines are preferred
(e.g. `Add clear-history confirmation dialog`). Keep unrelated changes in
separate commits.

## Reporting security issues

Please do **not** open a public issue for security problems (e.g. anything that
could leak clipboard contents). Instead, report it privately via GitHub's
[security advisories](https://github.com/doublehS2/pastewisp/security/advisories/new).
