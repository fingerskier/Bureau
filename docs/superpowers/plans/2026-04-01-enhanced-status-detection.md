# Enhanced Status Detection Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add screen content capture, visual-idle hash detection, and Claude Haiku CLI analysis to terminal status monitoring.

**Architecture:** Three-layer detection: CPU heuristic (existing) + screen hash staleness + Claude Haiku semantic analysis via `claude` CLI. Screen content captured per-platform via `read_screen()` on the driver, hashed each poll to detect visual staleness, and fed to Haiku every 5s for structured analysis (skipped when visually idle).

**Tech Stack:** Python 3.10+, Textual, psutil, hashlib, `claude` CLI (external), ctypes (Windows console buffer), AppleScript (macOS), `script` command (Linux)

---

### Task 1: Add TerminalAnalysis dataclass and Session fields

**Files:**
- Modify: `termdash/models.py:39-44` (after ActivityState enum)
- Modify: `termdash/models.py:117-122` (Session runtime fields)

- [ ] **Step 1: Add TerminalAnalysis dataclass to models.py**

Add after the `ActivityState` enum (line 44):

```python
@dataclass
class TerminalAnalysis:
    """Structured output from Claude Haiku terminal analysis."""
    state: str = "unknown"           # idle|working|error|blocked
    waiting_on_user: bool = False
    summary: str = ""
    detected_tool: str | None = None
    suggestions: list[str] = field(default_factory=list)
    has_errors: bool = False
    confidence: float = 0.0
    analyzed_at: Optional[datetime] = None
```

- [ ] **Step 2: Add new runtime fields to Session**

Add after `_cpu_history` (line 122):

```python
    screen_content: str = ""
    visually_idle: bool = False
    analysis: Optional[TerminalAnalysis] = None
    _screen_hash: str = field(default="", repr=False)
    _screen_idle_count: int = field(default=0, repr=False)
```

- [ ] **Step 3: Verify import works**

Run: `python -c "from termdash.models import TerminalAnalysis, Session; print('OK')"`

- [ ] **Step 4: Commit**

```bash
git add termdash/models.py
git commit -m "feat: add TerminalAnalysis dataclass and screen tracking fields to Session"
```

---

### Task 2: Add read_screen() to base driver and Windows implementation

**Files:**
- Modify: `termdash/platform/base.py:72-74` (after inject_text)
- Modify: `termdash/platform/windows.py:230-244` (after inject_text)

- [ ] **Step 1: Add read_screen() to TerminalDriver base**

Add after `inject_text` in `termdash/platform/base.py`:

```python
    def read_screen(self, window_handle: int, pid: int, lines: int = 50) -> str | None:
        """Read visible text from a terminal window. Optional — defaults to None."""
        return None
```

- [ ] **Step 2: Implement read_screen() on WindowsDriver**

Add to `termdash/platform/windows.py` after `inject_text`:

```python
    def read_screen(self, window_handle: int, pid: int, lines: int = 50) -> str | None:
        """Read the console screen buffer of a terminal process via ctypes."""
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.windll.kernel32
        STD_OUTPUT_HANDLE = -11

        # Save our own console state, then attach to target
        had_console = kernel32.FreeConsole()
        if not kernel32.AttachConsole(pid):
            # Re-attach to our own console
            if had_console:
                kernel32.AttachConsole(-1)  # ATTACH_PARENT_PROCESS
            return None

        try:
            handle = kernel32.GetStdHandle(STD_OUTPUT_HANDLE)
            if handle == -1:
                return None

            class CONSOLE_SCREEN_BUFFER_INFO(ctypes.Structure):
                _fields_ = [
                    ("dwSize", wintypes._COORD),
                    ("dwCursorPosition", wintypes._COORD),
                    ("wAttributes", wintypes.WORD),
                    ("srWindow", wintypes.SMALL_RECT),
                    ("dwMaximumWindowSize", wintypes._COORD),
                ]

            csbi = CONSOLE_SCREEN_BUFFER_INFO()
            if not kernel32.GetConsoleScreenBufferInfo(handle, ctypes.byref(csbi)):
                return None

            width = csbi.dwSize.X
            # Read from cursor position backwards, up to `lines` lines
            end_row = csbi.dwCursorPosition.Y
            start_row = max(0, end_row - lines + 1)
            total_chars = width * (end_row - start_row + 1)

            buf = ctypes.create_unicode_buffer(total_chars)
            coord = wintypes._COORD(0, start_row)
            chars_read = wintypes.DWORD()
            kernel32.ReadConsoleOutputCharacterW(
                handle, buf, total_chars, coord, ctypes.byref(chars_read)
            )

            # Split into lines and strip trailing whitespace
            raw = buf.value
            result_lines = []
            for i in range(end_row - start_row + 1):
                line = raw[i * width:(i + 1) * width].rstrip()
                result_lines.append(line)

            return "\n".join(result_lines)
        except Exception:
            return None
        finally:
            kernel32.FreeConsole()
            # Re-attach to parent console (Textual manages its own I/O)
            kernel32.AttachConsole(-1)
```

- [ ] **Step 3: Verify import works**

Run: `python -c "from termdash.platform.windows import WindowsDriver; d = WindowsDriver(); print('OK')"`

- [ ] **Step 4: Commit**

```bash
git add termdash/platform/base.py termdash/platform/windows.py
git commit -m "feat: add read_screen() to base driver and Windows console buffer implementation"
```

---

### Task 3: Implement read_screen() on macOS driver

**Files:**
- Modify: `termdash/platform/macos.py:159-174` (after inject_text)

- [ ] **Step 1: Add read_screen() to MacOSDriver**

Add after `inject_text` in `termdash/platform/macos.py`:

```python
    def read_screen(self, window_handle: int, pid: int, lines: int = 50) -> str | None:
        """Read Terminal.app window content via AppleScript."""
        try:
            content = self._osascript(
                'tell application "Terminal" to get contents of selected tab of front window'
            )
            if not content:
                return None
            # Return last N lines
            all_lines = content.splitlines()
            return "\n".join(all_lines[-lines:])
        except Exception:
            return None
```

- [ ] **Step 2: Commit**

```bash
git add termdash/platform/macos.py
git commit -m "feat: add read_screen() to macOS driver via AppleScript"
```

---

### Task 4: Implement read_screen() on Linux driver with script wrapper

**Files:**
- Modify: `termdash/platform/linux.py:1-10` (imports)
- Modify: `termdash/platform/linux.py:14-15` (class attributes)
- Modify: `termdash/platform/linux.py:25-56` (spawn method)
- Modify: `termdash/platform/linux.py:157-171` (after inject_text)

- [ ] **Step 1: Add log directory and tracking to LinuxDriver**

Add `tempfile` and `Path` imports at the top of `termdash/platform/linux.py`:

```python
import tempfile
from pathlib import Path
```

Add a class attribute to track log files:

```python
class LinuxDriver(TerminalDriver):
    """Basic Linux driver using subprocess and xdotool/wmctrl when available."""

    _log_dir: Path = Path(tempfile.gettempdir()) / "termdash_logs"
    _pid_logs: dict[int, Path] = {}  # pid -> log file path
```

- [ ] **Step 2: Modify spawn() to wrap shells in `script`**

Replace the spawn method to wrap in `script -qf <logfile>`:

```python
    def spawn(
        self,
        shell_type: ShellType,
        working_dir: str = "",
        startup_commands: list[str] | None = None,
        title: str = "",
    ) -> tuple[int, Optional[int]]:
        self._log_dir.mkdir(parents=True, exist_ok=True)

        terminal_cmds = [
            ["gnome-terminal", "--"],
            ["konsole", "-e"],
            ["xterm", "-e"],
        ]

        shell = self.shell_executable(shell_type)
        cwd = working_dir or None

        # Create a log file for output capture
        log_file = self._log_dir / f"termdash_{id(self)}_{len(self._pid_logs)}.log"
        log_file.touch()

        # Wrap shell command in `script` for output capture
        if startup_commands:
            chain = " && ".join(startup_commands)
            script_cmd = shell + ["-c", f"{chain} ; exec $SHELL"]
        else:
            script_cmd = shell

        wrapped = ["script", "-qf", str(log_file)] + script_cmd

        for term_cmd in terminal_cmds:
            try:
                cmd = term_cmd + wrapped
                proc = subprocess.Popen(cmd, cwd=cwd)
                self._pid_logs[proc.pid] = log_file
                return proc.pid, None
            except FileNotFoundError:
                continue

        # Fallback: bare shell with script wrapper
        proc = subprocess.Popen(wrapped, cwd=cwd)
        self._pid_logs[proc.pid] = log_file
        return proc.pid, None
```

- [ ] **Step 3: Add read_screen() to LinuxDriver**

Add after `inject_text`:

```python
    def read_screen(self, window_handle: int, pid: int, lines: int = 50) -> str | None:
        """Read terminal output from script log file."""
        log_file = self._pid_logs.get(pid)
        if not log_file or not log_file.exists():
            return None
        try:
            # Read last N lines from the log file
            content = log_file.read_text(errors="replace")
            all_lines = content.splitlines()
            return "\n".join(all_lines[-lines:])
        except Exception:
            return None
```

- [ ] **Step 4: Commit**

```bash
git add termdash/platform/linux.py
git commit -m "feat: add read_screen() to Linux driver with script output capture"
```

---

### Task 5: Create analyzer module for Claude CLI integration

**Files:**
- Create: `termdash/analyzer.py`

- [ ] **Step 1: Create termdash/analyzer.py**

```python
"""Claude Haiku terminal analysis via claude CLI."""

from __future__ import annotations

import json
import subprocess
from datetime import datetime

from .models import TerminalAnalysis

_PROMPT = """Analyze this terminal output. Return ONLY valid JSON with these fields:
- state: one of "idle", "working", "error", "blocked"
- waiting_on_user: boolean, true if the terminal is waiting for user input
- summary: string, one-line description of what the terminal is doing
- detected_tool: string or null, the primary tool/process running (e.g. "npm", "python", "gcc")
- suggestions: array of strings, any observations or warnings
- has_errors: boolean, true if error output is visible
- confidence: float 0-1, how confident you are in this analysis"""


def analyze_screen(content: str, timeout: int = 15) -> TerminalAnalysis | None:
    """Send terminal content to Claude Haiku via CLI and parse structured response."""
    if not content or not content.strip():
        return None

    # Truncate to last 50 lines to keep token usage low
    lines = content.splitlines()[-50:]
    truncated = "\n".join(lines)

    try:
        result = subprocess.run(
            ["claude", "-p", "--model", "haiku", _PROMPT],
            input=truncated,
            capture_output=True,
            text=True,
            timeout=timeout,
        )

        if result.returncode != 0:
            return None

        output = result.stdout.strip()

        # Extract JSON from response (handle markdown code fences)
        if "```" in output:
            # Extract content between code fences
            parts = output.split("```")
            for part in parts[1:]:
                # Skip the language identifier line if present
                json_str = part.strip()
                if json_str.startswith("json"):
                    json_str = json_str[4:].strip()
                if json_str.startswith("{"):
                    output = json_str.split("```")[0].strip()
                    break

        data = json.loads(output)

        return TerminalAnalysis(
            state=data.get("state", "unknown"),
            waiting_on_user=bool(data.get("waiting_on_user", False)),
            summary=str(data.get("summary", "")),
            detected_tool=data.get("detected_tool"),
            suggestions=list(data.get("suggestions", [])),
            has_errors=bool(data.get("has_errors", False)),
            confidence=float(data.get("confidence", 0.0)),
            analyzed_at=datetime.now(),
        )
    except (subprocess.TimeoutExpired, FileNotFoundError, json.JSONDecodeError, ValueError):
        return None
```

- [ ] **Step 2: Verify import works**

Run: `python -c "from termdash.analyzer import analyze_screen; print('OK')"`

- [ ] **Step 3: Commit**

```bash
git add termdash/analyzer.py
git commit -m "feat: add analyzer module for Claude Haiku CLI terminal analysis"
```

---

### Task 6: Add screen hash tracking and analysis to Manager

**Files:**
- Modify: `termdash/manager.py:1-15` (imports)
- Modify: `termdash/manager.py:78-130` (refresh_all and _classify_activity)
- Modify: `termdash/manager.py:132-136` (after get_all_sessions)

- [ ] **Step 1: Add imports to manager.py**

Add `hashlib` import and import `TerminalAnalysis`:

```python
import hashlib
```

Update the models import to include `TerminalAnalysis`:

```python
from .models import (
    ActivityState, Favorite, Group, Layout, LayoutWindow,
    Session, SessionStatus, TerminalAnalysis, WindowRect,
)
```

Add analyzer import:

```python
from .analyzer import analyze_screen
```

- [ ] **Step 2: Add screen capture and hashing to refresh_all()**

Add after the window title refresh block (after line 118 `session.window_title = ...`), still inside the `for pid, session` loop:

```python
            # Capture screen content and hash for visual idle detection
            if session.window_handle:
                content = self.driver.read_screen(session.window_handle, pid)
                if content:
                    session.screen_content = content
                    # Hash last ~20 lines for staleness detection
                    tail = "\n".join(content.splitlines()[-20:])
                    new_hash = hashlib.md5(tail.encode()).hexdigest()
                    if new_hash == session._screen_hash:
                        session._screen_idle_count += 1
                    else:
                        session._screen_idle_count = 0
                    session._screen_hash = new_hash
                    session.visually_idle = session._screen_idle_count >= 3
```

- [ ] **Step 3: Update _classify_activity to use analysis and screen hash**

Replace the `_classify_activity` method:

```python
    def _classify_activity(self, session: Session) -> ActivityState:
        """Classify activity using analysis > screen hash > CPU heuristic."""
        # Priority 1: Haiku analysis (if fresh, < 10s old)
        if session.analysis and session.analysis.analyzed_at:
            age = (datetime.now() - session.analysis.analyzed_at).total_seconds()
            if age < 10:
                state_map = {
                    "working": ActivityState.WORKING,
                    "idle": ActivityState.IDLE,
                    "error": ActivityState.WORKING,  # errors are active state
                    "blocked": ActivityState.WAITING,
                }
                return state_map.get(session.analysis.state, ActivityState.UNKNOWN)

        # Priority 2: Screen hash — if visually idle AND CPU idle
        if session.visually_idle:
            cpu_history = session._cpu_history
            if cpu_history and all(c < self._CPU_IDLE_THRESHOLD for c in cpu_history[-3:]):
                return ActivityState.IDLE

        # Priority 3: CPU heuristic (existing logic)
        cpu_history = session._cpu_history
        if not cpu_history:
            return ActivityState.UNKNOWN
        recent = cpu_history[-3:] if len(cpu_history) >= 3 else cpu_history
        avg = sum(recent) / len(recent)
        if avg >= self._CPU_WORKING_THRESHOLD:
            return ActivityState.WORKING
        if all(c < self._CPU_IDLE_THRESHOLD for c in recent) and len(recent) >= 2:
            return ActivityState.IDLE
        return ActivityState.WAITING
```

Update the call site in `refresh_all()` — change `session.activity = self._classify_activity(session._cpu_history)` to:

```python
            session.activity = self._classify_activity(session)
```

- [ ] **Step 4: Add analyze_sessions() method**

Add after `get_all_sessions()`:

```python
    def analyze_sessions(self):
        """Run Claude Haiku analysis on sessions with fresh screen content."""
        for session in self.get_live_sessions():
            if session.visually_idle or not session.screen_content:
                continue
            result = analyze_screen(session.screen_content)
            if result:
                session.analysis = result
```

- [ ] **Step 5: Verify import works**

Run: `python -c "from termdash.manager import Manager; print('OK')"`

- [ ] **Step 6: Commit**

```bash
git add termdash/manager.py
git commit -m "feat: add screen hash tracking and Haiku analysis integration to Manager"
```

---

### Task 7: Update SessionTable to display analysis data

**Files:**
- Modify: `termdash/widgets/session_table.py`

- [ ] **Step 1: Update session_table.py to show analysis**

Replace the full file content:

```python
"""Live session table widget."""

from __future__ import annotations

from datetime import datetime

from textual.widgets import DataTable

from ..models import ActivityState, Session, SessionStatus


# Activity indicators (terminal-safe characters)
_ACTIVITY_ICONS = {
    ActivityState.WORKING: "[bold green]>>>[/]",
    ActivityState.WAITING: "[yellow]...[/]",
    ActivityState.IDLE:    "[dim]zzz[/]",
    ActivityState.UNKNOWN: "[dim]?[/]",
}


class SessionTable(DataTable):
    """DataTable showing tracked terminal sessions with live status."""

    def on_mount(self):
        self.add_columns("PID", "Label", "Shell", "Dir", "Uptime", "Mem", "Activity", "Summary")
        self.cursor_type = "row"

    def refresh_sessions(self, sessions: list[Session]):
        """Clear and repopulate the table from a list of sessions."""
        self.clear()
        for session in sessions:
            uptime = ""
            if session.spawned_at:
                delta = datetime.now() - session.spawned_at
                mins = int(delta.total_seconds() // 60)
                if mins >= 60:
                    uptime = f"{mins // 60}h{mins % 60}m"
                else:
                    uptime = f"{mins}m"

            if session.status == SessionStatus.DEAD:
                activity = "[red]DEAD[/]"
            elif session.analysis and session.analysis.has_errors:
                activity = "[bold red]ERR[/]"
            else:
                activity = _ACTIVITY_ICONS.get(session.activity, "?")

            # Build summary from analysis or window title
            summary = ""
            if session.analysis and session.analysis.summary:
                tool = session.analysis.detected_tool
                summary = f"[{tool}] " if tool else ""
                summary += session.analysis.summary
                if session.analysis.waiting_on_user:
                    summary += " [yellow](input)[/]"
            elif session.window_title:
                summary = _truncate(session.window_title, 35)

            self.add_row(
                str(session.pid),
                session.label or "\u2014",
                session.shell_type.value,
                _truncate(session.working_dir, 18),
                uptime,
                f"{session.memory_mb:.0f}MB" if session.memory_mb else "\u2014",
                activity,
                _truncate(summary, 40) if summary else "\u2014",
                key=str(session.pid),
            )

    def get_selected_pid(self) -> int | None:
        """Return the PID of the currently selected row, or None."""
        if self.cursor_row is not None:
            row = self.get_row_at(self.cursor_row)
            return int(row[0])
        return None


def _truncate(s: str, max_len: int) -> str:
    return s if len(s) <= max_len else "\u2026" + s[-(max_len - 1):]
```

- [ ] **Step 2: Commit**

```bash
git add termdash/widgets/session_table.py
git commit -m "feat: display Haiku analysis summary and error badges in session table"
```

---

### Task 8: Add 5-second analysis timer to app

**Files:**
- Modify: `termdash/app.py:86` (__init__, add timer field)
- Modify: `termdash/app.py:99-106` (on_mount, add analysis timer)
- Modify: `termdash/app.py:329-332` (on_unmount, stop analysis timer)

- [ ] **Step 1: Add analysis timer field in __init__**

In `termdash/app.py`, add after `self._poll_timer: Timer | None = None`:

```python
        self._analysis_timer: Timer | None = None
```

- [ ] **Step 2: Start analysis timer in on_mount**

In `on_mount`, add after the poll timer line (`self._poll_timer = self.set_interval(2.0, ...)`):

```python
        self._analysis_timer = self.set_interval(5.0, self._analyze_sessions)
```

- [ ] **Step 3: Add _analyze_sessions method**

Add after `_poll_sessions`:

```python
    def _analyze_sessions(self):
        """Run Claude Haiku analysis on active sessions (background)."""
        self.run_worker(self._run_analysis, thread=True)

    def _run_analysis(self):
        """Worker thread for Haiku analysis (subprocess calls block)."""
        self.manager.analyze_sessions()
```

- [ ] **Step 4: Stop analysis timer in on_unmount**

In `on_unmount`, add after the poll timer stop:

```python
        if self._analysis_timer:
            self._analysis_timer.stop()
```

- [ ] **Step 5: Verify full import chain**

Run: `python -c "from termdash.app import TermDashApp; print('OK')"`

- [ ] **Step 6: Commit**

```bash
git add termdash/app.py
git commit -m "feat: add 5-second analysis timer with background worker for Haiku calls"
```

---

### Task 9: Final verification and commit

- [ ] **Step 1: Run full import verification**

```bash
python -c "
from termdash.models import TerminalAnalysis, Session, ActivityState
from termdash.analyzer import analyze_screen
from termdash.manager import Manager
from termdash.platform import get_driver
from termdash.widgets.session_table import SessionTable
from termdash.app import TermDashApp
print('All imports OK')
d = get_driver()
print(f'Driver: {type(d).__name__}')
print(f'Has read_screen: {hasattr(d, \"read_screen\")}')
"
```

Expected: All imports OK, Driver: WindowsDriver, Has read_screen: True

- [ ] **Step 2: Test that app launches**

Run: `python -m termdash` — verify it starts without errors, spawns a terminal, and the Summary column appears.

- [ ] **Step 3: Final commit if any loose changes**

```bash
git add -A
git commit -m "feat: complete enhanced status detection — screen hash + Claude Haiku analysis"
```
