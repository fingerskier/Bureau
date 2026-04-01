# Enhanced Terminal Status Detection

## Problem

The current activity classifier relies solely on CPU usage sampling via psutil. This misses important context: a terminal showing a wall of error output at 0% CPU looks "idle" to the classifier, and a terminal waiting on user input looks the same as one that just finished a build.

## Solution

Add two new detection layers that complement the existing CPU heuristic:

1. **Screen hash** — capture and hash visible terminal output to detect visual staleness
2. **Claude Haiku analysis** — send terminal content to Haiku via `claude` CLI for semantic understanding

## Architecture

### Screen Capture

Add `read_screen(window_handle) -> str | None` to `TerminalDriver` base class (default returns `None`).

**Platform implementations:**

| Platform | Method |
|----------|--------|
| Windows | `ReadConsoleOutputCharacter` via win32 — reads text from the console screen buffer using the console handle derived from the window handle |
| macOS | AppleScript: `tell application "Terminal" to get contents of selected tab of front window` |
| Linux | At spawn time, wrap the shell in `script -q /tmp/termdash_<pid>.log`. On read, tail the log file for the last N lines |

Returns the last ~50 lines of visible terminal content as a string.

### Screen Hash — Visual Idle Detection

On each 2-second poll in `Manager.refresh_all()`:

1. Call `driver.read_screen(hwnd)` for each live session
2. Hash the last ~20 lines (`hashlib.md5` — speed matters, not security)
3. Store hash on `Session._screen_hash` and track previous hash in `Session._prev_screen_hash`
4. If hash unchanged for 3+ consecutive polls, set `session.visually_idle = True`
5. If hash changes, reset the counter and set `visually_idle = False`

New fields on `Session`:
- `screen_content: str = ""` — last captured output (last ~50 lines)
- `visually_idle: bool = False`
- `_screen_hash: str = ""` (runtime only)
- `_screen_idle_count: int = 0` (runtime only)

### Claude Haiku Analysis

A separate 5-second timer in `TermDashApp` calls `Manager.analyze_sessions()`.

For each live session where `visually_idle is False` and `screen_content` is non-empty:

1. Invoke `claude` CLI via subprocess:
   ```
   echo "<screen_content>" | claude -p --model haiku "<prompt>"
   ```
2. Parse JSON response
3. Store result on `Session.analysis`

**Prompt:**
```
Analyze this terminal output. Return ONLY valid JSON with these fields:
- state: one of "idle", "working", "error", "blocked"
- waiting_on_user: boolean, true if the terminal is waiting for user input
- summary: string, one-line description of what the terminal is doing
- detected_tool: string or null, the primary tool/process running (e.g. "npm", "python", "gcc")
- suggestions: array of strings, any observations or warnings
- has_errors: boolean, true if error output is visible
- confidence: float 0-1, how confident you are in this analysis
```

**Skip conditions** (to control cost/noise):
- `visually_idle is True` — no point analyzing unchanged output
- `screen_content` is empty
- Session is DEAD

**Schema:**
```python
@dataclass
class TerminalAnalysis:
    state: str = "unknown"           # idle|working|error|blocked
    waiting_on_user: bool = False
    summary: str = ""
    detected_tool: str | None = None
    suggestions: list[str] = field(default_factory=list)
    has_errors: bool = False
    confidence: float = 0.0
    analyzed_at: datetime | None = None
```

New field on `Session`:
- `analysis: TerminalAnalysis | None = None`

### Updated Activity Classification

`Manager._classify_activity()` updated to use priority order:

1. **Haiku result** (if fresh, < 10s old): use `analysis.state` directly
2. **Screen hash**: if `visually_idle` and CPU idle, classify as `IDLE`
3. **CPU heuristic** (existing): fallback when no screen data available

### Dashboard Display

`SessionTable` updated to show Haiku analysis when available:
- Activity column shows Haiku `state` instead of CPU-derived state when analysis is fresh
- Tooltip or expanded row could show `summary`, `detected_tool`, `suggestions`
- Error badge when `has_errors is True`

## Files Modified

| File | Changes |
|------|---------|
| `termdash/models.py` | Add `TerminalAnalysis` dataclass, new `Session` fields |
| `termdash/platform/base.py` | Add `read_screen()` to `TerminalDriver` |
| `termdash/platform/windows.py` | Implement `read_screen()` via win32 console buffer |
| `termdash/platform/macos.py` | Implement `read_screen()` via AppleScript |
| `termdash/platform/linux.py` | Implement `read_screen()` via `script` log tailing, modify `spawn()` |
| `termdash/manager.py` | Screen hash tracking, `analyze_sessions()`, updated classifier |
| `termdash/widgets/session_table.py` | Display analysis data |
| `termdash/app.py` | Add 5-second analysis timer |

## Dependencies

- `claude` CLI must be on PATH (for Haiku analysis)
- No new Python packages required

## Verification

1. Spawn a terminal, run a command — dashboard shows "working" with tool detection
2. Let terminal sit idle — screen hash detects staleness, Haiku calls stop
3. Run a command that errors — `has_errors` shows true, error badge appears
4. Check that Haiku is not called when terminal is visually idle (cost control)
