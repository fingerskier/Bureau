"""Process lifecycle manager — spawn, track, reconnect, arrange."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

import psutil

from .db import Database
from .models import (
    Favorite, Group, Layout, LayoutWindow,
    Session, SessionStatus, WindowRect,
)
from .platform.base import TerminalDriver


class Manager:
    def __init__(self, db: Database, driver: TerminalDriver):
        self.db = db
        self.driver = driver
        self.sessions: dict[int, Session] = {}  # pid -> Session

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
        self.sessions[pid] = session
        return session

    def kill_session(self, pid: int) -> bool:
        success = self.driver.kill(pid)
        if pid in self.sessions:
            self.sessions[pid].status = SessionStatus.DEAD
            self.db.save_session(self.sessions[pid])
        return success

    # --- Health ---

    def refresh_all(self):
        """Poll all tracked sessions for liveness and resource usage."""
        dead_pids = []
        for pid, session in self.sessions.items():
            if not self.driver.is_alive(pid):
                session.status = SessionStatus.DEAD
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

            # Refresh window handle if lost
            if session.window_handle is None:
                hwnd = self.driver.find_window_for_pid(pid)
                if hwnd:
                    session.window_handle = hwnd
                    self.db.save_session(session)

            # Refresh window title
            if session.window_handle:
                session.window_title = self.driver.get_window_title(session.window_handle)

    def get_live_sessions(self) -> list[Session]:
        return [s for s in self.sessions.values() if s.status == SessionStatus.ALIVE]

    def get_all_sessions(self) -> list[Session]:
        return list(self.sessions.values())

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
