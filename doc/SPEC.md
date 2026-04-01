# TermDash

A Python + Textual TUI for spawning, tracking, and managing native terminal windows.

## Architecture

```
termdash/
├── __main__.py              # Entry point
├── app.py                   # Textual application
├── db.py                    # SQLite persistence layer
├── models.py                # Data models (dataclasses)
├── manager.py               # Process lifecycle + reconnection
├── platform/
│   ├── __init__.py          # Auto-detect and export platform driver
│   ├── base.py              # Abstract base (TerminalDriver)
│   ├── windows.py           # win32gui + CREATE_NEW_CONSOLE
│   └── macos.py             # osascript / AppleScript
└── widgets/
    ├── __init__.py
    ├── session_table.py     # Live session list with status
    ├── group_browser.py     # Favorites & groups panel
    └── spawn_dialog.py      # New terminal dialog
```

## Install

```bash
pip install textual psutil
# Windows: pip install pywin32
```

## Run

```bash
python -m termdash
```
