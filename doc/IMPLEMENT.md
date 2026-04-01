# Bureau (TermDash) — Implementation Plan

A phased roadmap for evolving the `example/` reference code into a production-ready terminal management TUI.

> Reqall tracking: project **fingerskier/Bureau** #1168, records #1219–#1223
>
> **Status: All 5 phases implemented.** See `termdash/` package.

---

## Phase 1 — Package Restructure

**Goal:** Transform the flat `example/` files into the `termdash/` package layout defined in `doc/SPEC.md`.

| Task | Detail |
|------|--------|
| Create `termdash/__main__.py` | Entry point: `python -m termdash` |
| Create `termdash/platform/base.py` | Abstract `TerminalDriver` with the interface currently implied by `windows.py` and `macos.py` — `spawn`, `is_alive`, `kill`, `focus_window`, `get_window_rect`, `set_window_rect`, `get_window_title`, `find_window_for_pid`, `get_screen_size`, `minimize_window`, `restore_window` |
| Create `termdash/platform/__init__.py` | Auto-detect OS and export the correct driver |
| Move platform drivers | `example/windows.py` → `termdash/platform/windows.py`, `example/macos.py` → `termdash/platform/macos.py` |
| Extract widgets from `app.py` | `SessionTable` → `termdash/widgets/session_table.py`, `GroupBrowser` → `termdash/widgets/group_browser.py`, `SpawnDialog` / `SaveFavoriteDialog` → `termdash/widgets/spawn_dialog.py` |
| Move core modules | `models.py`, `db.py`, `manager.py`, `app.py` → `termdash/` |
| Update `pyproject.toml` | Add `[project.scripts]` entry point, set package root, update metadata |

**Verification:** `pip install -e .` succeeds, `python -m termdash` launches the dashboard, existing functionality works unchanged.

---

## Phase 2 — Command / Text Injection

**Goal:** Send text or commands into a running terminal session from the dashboard.

| Task | Detail |
|------|--------|
| Extend `TerminalDriver` interface | Add `inject_text(hwnd_or_pid, text: str) -> bool` |
| Windows implementation | `win32gui.SendMessage` / `WriteConsoleInput` targeting the terminal window handle |
| macOS implementation | `osascript` keystroke injection into Terminal.app / iTerm2 |
| Linux implementation | `xdotool type` for X11 sessions, or pty write for locally-spawned shells |
| Add UI action | Keybind `i` → opens an input dialog, confirms, then injects into the selected session |
| Safety | Confirmation dialog before injection; log injected commands |

**Verification:** Select a running session, press `i`, type a command — it appears and executes in the target terminal.

---

## Phase 3 — Advanced Status Gleaning

**Goal:** Move beyond basic alive/dead + CPU/memory to richer terminal state awareness.

| Task | Detail |
|------|--------|
| State heuristics | Classify sessions as **working** (high CPU), **waiting** (blocked on input), or **idle** (low activity) based on psutil process stats over a sliding window |
| Window title capture | Poll `get_window_title()` and display in the session table — many shells embed CWD or running command in the title |
| Optional output capture | Windows: ConPTY; Unix: pty pair — capture last N lines of terminal output for preview |
| Dashboard indicators | Replace simple status icons with richer indicators (spinner for working, prompt icon for waiting, dim for idle, error badge) |

**Verification:** Launch a terminal, run a long process — dashboard shows "working"; let it finish — dashboard transitions to "idle."

---

## Phase 4 — UI Polish & QoL

**Goal:** Fill in the UX gaps and add configuration portability.

| Task | Detail |
|------|--------|
| Group picker dialog | Replace the current "launch first group" behavior with a selection dialog listing all groups |
| Search / filter | Add a filter input above the session table and favorites list (fuzzy match on label, shell, CWD) |
| Config export / import | Serialize favorites, groups, and layouts to a JSON file; import with merge-or-replace semantics |
| Raspberry Pi lightweight mode | Reduce polling frequency, disable window-rect operations (no desktop on headless), auto-detect via `platform.machine()` |

**Verification:** Export config → delete DB → import config → favorites and groups restored. Filter narrows session list as expected.

---

## Phase 5 — Linux Platform Driver

**Goal:** First-class Linux support including X11, Wayland, and Raspberry Pi OS.

| Task | Detail |
|------|--------|
| Create `termdash/platform/linux.py` | Implement `TerminalDriver` for Linux |
| X11 window management | `python-xlib` or subprocess calls to `wmctrl` / `xdotool` for position, focus, minimize, restore |
| Wayland considerations | Detect Wayland session; use compositor-specific IPC (sway, Hyprland) where available; degrade gracefully |
| Shell detection | Map common Linux terminals: gnome-terminal, konsole, alacritty, kitty, xterm, foot |
| RPi OS testing | Validate on Raspberry Pi OS (Bookworm) with both X11 and Wayland (labwc) |

**Verification:** On a Linux desktop, `python -m termdash` spawns terminals, tracks PIDs, captures/applies window layouts.

---

## Dependency Summary

```
Phase 1 ──► Phase 2 ──► Phase 3
                │
                └──► Phase 4 (independent of Phase 3)
Phase 1 ──► Phase 5 (independent of Phases 2–4)
```

Phase 1 is the prerequisite for all other work. Phases 2–5 can proceed in parallel once the package structure is in place, though Phases 2→3 have a natural progression.
