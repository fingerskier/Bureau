"""Process lifecycle manager — spawn, track, reconnect, arrange."""

from __future__ import annotations

from datetime import datetime
import hashlib
import threading
from typing import Optional

import psutil

from .db import Database
from .models import (
    ActivityState, Favorite, Group, Layout, LayoutWindow,
    Session, SessionStatus, TerminalAnalysis, WindowRect,
)
from .platform.base import TerminalDriver
from .analyzer import analyze_screen


class Manager:
    def __init__(self, db: Database, driver: TerminalDriver):
        self.db = db
        self.driver = driver
        self.sessions: dict[int, Session] = {}  # pid -> Session
        self._lock = threading.Lock()  # guards self.sessions

    # --- Lifecycle ---

    def spawn_from_favorite(self, fav: Favorite, group_id: Optional[int] = None) -> Session:
        pid, hwnd = self.driver.spawn(
            shell_type=fav.shell_type,
            working_dir=fav.working_dir,
            startup_commands=fav.startup_commands,
            title=fav.label,
        )
        session = Session(
            pid=pid,
            window_handle=hwnd,
            favorite_id=fav.id,
            group_id=group_id,
            label=fav.label,
            shell_type=fav.shell_type,
            working_dir=fav.working_dir,
            spawned_at=datetime.now(),
            status=SessionStatus.ALIVE,
        )
        session = self.db.save_session(session)
        with self._lock:
            self.sessions[pid] = session
        return session

    def spawn_quick(self, shell_type, working_dir: str = "", label: str = "") -> Session:
        """Spawn a terminal without a saved favorite."""
        from .models import ShellType
        pid, hwnd = self.driver.spawn(
            shell_type=shell_type,
            working_dir=working_dir,
            title=label,
        )
        session = Session(
            pid=pid,
            window_handle=hwnd,
            label=label or shell_type.value,
            shell_type=shell_type,
            working_dir=working_dir,
            spawned_at=datetime.now(),
            status=SessionStatus.ALIVE,
        )
        session = self.db.save_session(session)
        with self._lock:
            self.sessions[pid] = session
        return session

    def kill_session(self, pid: int) -> bool:
        success = self.driver.kill(pid)
        with self._lock:
            session = self.sessions.pop(pid, None)
        if session:
            session.status = SessionStatus.DEAD
            self.db.save_session(session)
        return success

    # --- Health ---

    # Number of CPU samples to keep for activity classification
    _CPU_HISTORY_LEN = 5
    _CPU_WORKING_THRESHOLD = 5.0   # % — above this = working
    _CPU_IDLE_THRESHOLD = 0.5      # % — below this for all samples = idle

    def refresh_all(self):
        """Poll all tracked sessions for liveness and resource usage."""
        with self._lock:
            snapshot = list(self.sessions.items())

        dead_pids = []
        for pid, session in snapshot:
            if not self.driver.is_alive(pid):
                session.status = SessionStatus.DEAD
                session.activity = ActivityState.UNKNOWN
                self.db.save_session(session)
                dead_pids.append(pid)
                continue

            try:
                proc = psutil.Process(pid)
                session.cpu_percent = proc.cpu_percent(interval=0)
                mem = proc.memory_info()
                session.memory_mb = mem.rss / (1024 * 1024)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                session.cpu_percent = 0
                session.memory_mb = 0

            # Track CPU history and classify activity
            session._cpu_history.append(session.cpu_percent)
            if len(session._cpu_history) > self._CPU_HISTORY_LEN:
                session._cpu_history = session._cpu_history[-self._CPU_HISTORY_LEN:]
            session.activity = self._classify_activity(session)

            # Refresh window handle if lost
            if session.window_handle is None:
                hwnd = self.driver.find_window_for_pid(pid)
                if hwnd:
                    session.window_handle = hwnd
                    self.db.save_session(session)

            # Refresh window title
            if session.window_handle:
                session.window_title = self.driver.get_window_title(session.window_handle)

            # Screen capture moved to analyze_sessions() — runs in background
            # thread to avoid FreeConsole/AttachConsole disrupting Textual

        # Remove dead sessions from tracking
        if dead_pids:
            with self._lock:
                for pid in dead_pids:
                    self.sessions.pop(pid, None)

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

    def get_live_sessions(self) -> list[Session]:
        with self._lock:
            return [s for s in self.sessions.values() if s.status == SessionStatus.ALIVE]

    def get_all_sessions(self) -> list[Session]:
        with self._lock:
            return list(self.sessions.values())

    def analyze_sessions(self):
        """Capture screen content, update hashes, and run Haiku analysis.

        Called from a background worker thread — safe to use
        FreeConsole/AttachConsole here without disrupting Textual.
        """
        # Snapshot live sessions under lock; iterate outside lock
        for session in self.get_live_sessions():
            # Screen capture (safe in background thread)
            if session.window_handle:
                try:
                    content = self.driver.read_screen(session.window_handle, session.pid)
                except Exception:
                    content = None
                if content:
                    session.screen_content = content
                    tail = "\n".join(content.splitlines()[-20:])
                    new_hash = hashlib.md5(tail.encode()).hexdigest()
                    if new_hash == session._screen_hash:
                        session._screen_idle_count += 1
                    else:
                        session._screen_idle_count = 0
                    session._screen_hash = new_hash
                    session.visually_idle = session._screen_idle_count >= 3

            # Haiku analysis (skip if visually idle or no content)
            if session.visually_idle or not session.screen_content:
                continue
            result = analyze_screen(session.screen_content)
            if result:
                session.analysis = result

    # --- Reconnection ---

    def reconnect(self):
        """
        On startup, attempt to reattach to terminals from the previous session.
        Match by PID — if still alive and looks like the right process, reclaim it.
        """
        previous = self.db.list_sessions(status=SessionStatus.ALIVE)
        reconnected = 0

        for session in previous:
            if self.driver.is_alive(session.pid):
                # Verify it's plausibly the same process
                try:
                    proc = psutil.Process(session.pid)
                    proc_name = proc.name().lower()
                    # Rough heuristic: does the process name match the shell type?
                    shell_names = {
                        "powershell": ["powershell"],
                        "pwsh": ["pwsh"],
                        "cmd": ["cmd", "conhost"],
                        "wsl": ["wsl", "bash"],
                        "git_bash": ["bash", "git"],
                        "bash": ["bash"],
                        "zsh": ["zsh"],
                    }
                    expected = shell_names.get(session.shell_type.value, [])
                    if not any(name in proc_name for name in expected):
                        # PID reuse — different process now
                        session.status = SessionStatus.DEAD
                        self.db.save_session(session)
                        continue
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    session.status = SessionStatus.DEAD
                    self.db.save_session(session)
                    continue

                # Try to re-find the window handle
                hwnd = self.driver.find_window_for_pid(session.pid)
                if hwnd:
                    session.window_handle = hwnd
                session.status = SessionStatus.ALIVE
                self.db.save_session(session)
                with self._lock:
                    self.sessions[session.pid] = session
                reconnected += 1
            else:
                session.status = SessionStatus.DEAD
                self.db.save_session(session)

        return reconnected

    # --- Groups ---

    def launch_group(self, group: Group) -> list[Session]:
        """Launch all favorites in a group, optionally applying its layout."""
        favorites = self.db.get_group_favorites(group.id)
        sessions = []
        for fav in favorites:
            session = self.spawn_from_favorite(fav, group_id=group.id)
            sessions.append(session)

        # Apply layout if one is associated
        if group.layout_id:
            self.apply_layout(group.layout_id, sessions)

        return sessions

    # --- Layouts ---

    def capture_layout(self, name: str) -> Optional[Layout]:
        """Snapshot current window positions into a named layout."""
        w, h = self.driver.get_screen_size()
        layout = Layout(name=name, monitor_width=w, monitor_height=h)
        layout = self.db.upsert_layout(layout)

        windows = []
        for session in self.get_live_sessions():
            if session.window_handle and session.favorite_id:
                rect = self.driver.get_window_rect(session.window_handle)
                if rect:
                    windows.append(LayoutWindow(
                        layout_id=layout.id,
                        favorite_id=session.favorite_id,
                        rect=rect,
                    ))

        self.db.save_layout_windows(layout.id, windows)
        return layout

    def apply_layout(self, layout_id: int, sessions: Optional[list[Session]] = None):
        """Restore windows to saved positions."""
        layout_windows = self.db.get_layout_windows(layout_id)
        targets = sessions or self.get_live_sessions()

        # Map favorite_id -> session for matching
        fav_map: dict[int, Session] = {}
        for s in targets:
            if s.favorite_id:
                fav_map[s.favorite_id] = s

        for lw in layout_windows:
            session = fav_map.get(lw.favorite_id)
            if session and session.window_handle:
                self.driver.set_window_rect(session.window_handle, lw.rect)

    def focus_session(self, pid: int) -> bool:
        session = self.sessions.get(pid)
        if session and session.window_handle:
            return self.driver.focus_window(session.window_handle)
        return False

    def inject_text(self, pid: int, text: str) -> bool:
        """Send text to a running terminal session."""
        session = self.sessions.get(pid)
        if session and session.window_handle and session.status == SessionStatus.ALIVE:
            return self.driver.inject_text(session.window_handle, text)
        return False
