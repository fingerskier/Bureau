"""TermDash — Textual TUI application."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.reactive import reactive
from textual.timer import Timer
from textual.widgets import Footer, Header, Input, Static

from .db import Database
from .manager import Manager
from .models import Favorite, SessionStatus
from .platform import get_driver
from .widgets import (
    GroupBrowser, GroupPickerDialog, InjectDialog,
    SaveFavoriteDialog, SessionTable, SpawnDialog,
)


class TermDashApp(App):
    """Terminal Dashboard."""

    TITLE = "TermDash"
    SUB_TITLE = "Terminal Manager"

    CSS = """
    #main {
        height: 1fr;
    }
    #sessions-panel {
        width: 3fr;
        border: round $accent;
        padding: 0 1;
    }
    #sidebar {
        width: 1fr;
        min-width: 28;
        border: round $primary;
        padding: 0 1;
    }
    #status-bar {
        height: 1;
        dock: bottom;
        background: $accent;
        color: $text;
        padding: 0 1;
    }
    .section-title {
        text-style: bold;
        margin: 1 0 0 0;
    }
    #filter-input {
        height: 1;
        margin: 0 0 1 0;
    }
    """

    BINDINGS = [
        Binding("ctrl+n", "spawn", "New Terminal", priority=True),
        Binding("ctrl+k", "kill", "Kill Selected", priority=True),
        Binding("ctrl+f", "focus_term", "Focus Window", priority=True),
        Binding("ctrl+s", "save_favorite", "Save Favorite", priority=True),
        Binding("ctrl+g", "launch_group", "Launch Group", priority=True),
        Binding("ctrl+i", "inject", "Inject Text", priority=True),
        Binding("ctrl+l", "capture_layout", "Capture Layout", priority=True),
        Binding("slash", "filter", "Filter", priority=True),
        Binding("escape", "unfocus_filter", "Back to Table", priority=False),
        Binding("ctrl+r", "refresh", "Refresh", priority=True),
        Binding("ctrl+q", "quit", "Quit", priority=True),
    ]

    session_count: reactive[int] = reactive(0)
    filter_text: reactive[str] = reactive("")

    def __init__(self):
        super().__init__()
        self.database = Database()
        self.platform_driver = get_driver()
        self.manager = Manager(self.database, self.platform_driver)
        self._poll_timer: Timer | None = None
        self._analysis_timer: Timer | None = None

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal(id="main"):
            with Vertical(id="sessions-panel"):
                yield Static("Sessions", classes="section-title")
                yield Input(placeholder="type to filter...", id="filter-input")
                yield SessionTable(id="session-table")
            yield GroupBrowser(id="sidebar")
        yield Static("Ready", id="status-bar")
        yield Footer()

    def on_mount(self):
        reconnected = self.manager.reconnect()
        self._set_status(f"Reconnected {reconnected} session(s)")
        self._refresh_sidebar()
        self._poll_timer = self.set_interval(2.0, self._poll_sessions)
        self._analysis_timer = self.set_interval(5.0, self._analyze_sessions)
        self._refresh_table()
        # Focus the session table so keybindings work immediately
        self.query_one("#session-table", SessionTable).focus()

    def _set_status(self, msg: str):
        self.query_one("#status-bar", Static).update(msg)

    # -- Filter --

    def on_input_changed(self, event: Input.Changed):
        if event.input.id == "filter-input":
            self.filter_text = event.value
            self._refresh_table()

    def action_filter(self):
        self.query_one("#filter-input", Input).focus()

    def action_unfocus_filter(self):
        self.query_one("#session-table", SessionTable).focus()

    # -- Table --

    def _refresh_table(self):
        self.manager.refresh_all()
        sessions = self.manager.get_all_sessions()

        # Apply filter
        if self.filter_text:
            needle = self.filter_text.lower()
            sessions = [
                s for s in sessions
                if needle in s.label.lower()
                or needle in s.shell_type.value.lower()
                or needle in s.working_dir.lower()
                or needle in s.window_title.lower()
                or needle in str(s.pid)
            ]

        table = self.query_one("#session-table", SessionTable)
        table.refresh_sessions(sessions)
        self.session_count = len(self.manager.get_live_sessions())

    def _poll_sessions(self):
        self._refresh_table()

    def _analyze_sessions(self):
        """Run Claude Haiku analysis on active sessions (background)."""
        self.run_worker(self._run_analysis, thread=True)

    def _run_analysis(self):
        """Worker thread for Haiku analysis (subprocess calls block)."""
        self.manager.analyze_sessions()

    # -- Sidebar --

    def _refresh_sidebar(self):
        browser = self.query_one("#sidebar", GroupBrowser)
        browser.refresh_data(self.database.list_favorites(), self.database.list_groups())

    # -- Actions --

    def action_spawn(self):
        self.push_screen(SpawnDialog(), self._on_spawn_result)

    def _on_spawn_result(self, result: Favorite | None):
        if result:
            session = self.manager.spawn_quick(
                shell_type=result.shell_type,
                working_dir=result.working_dir,
                label=result.label,
            )
            if result.startup_commands:
                self.manager.kill_session(session.pid)
                session = self.manager.spawn_from_favorite(result)
            self._set_status(f"Spawned {result.label} (PID {session.pid})")
            self._refresh_table()

    def action_kill(self):
        table = self.query_one("#session-table", SessionTable)
        pid = table.get_selected_pid()
        if pid is not None:
            self.manager.kill_session(pid)
            self._set_status(f"Killed PID {pid}")
            self._refresh_table()

    def action_focus_term(self):
        table = self.query_one("#session-table", SessionTable)
        pid = table.get_selected_pid()
        if pid is not None:
            self.manager.focus_session(pid)

    def action_save_favorite(self):
        table = self.query_one("#session-table", SessionTable)
        pid = table.get_selected_pid()
        if pid is not None:
            session = self.manager.sessions.get(pid)
            if session:
                self.push_screen(
                    SaveFavoriteDialog(),
                    lambda name: self._do_save_favorite(session, name),
                )

    def _do_save_favorite(self, session, name: str | None):
        if name:
            # Glean the actual cwd from the live process (may differ from spawn dir)
            import psutil
            cwd = session.working_dir
            try:
                proc = psutil.Process(session.pid)
                cwd = proc.cwd() or cwd
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
            fav = Favorite(
                label=name,
                shell_type=session.shell_type,
                working_dir=cwd,
            )
            self.database.upsert_favorite(fav)
            self._set_status(f"Saved favorite: {name} ({cwd})")
            self._refresh_sidebar()

    def action_launch_group(self):
        groups = self.database.list_groups()
        if not groups:
            self._set_status("No groups defined yet")
            return
        if len(groups) == 1:
            self._do_launch_group(groups[0].id)
        else:
            self.push_screen(GroupPickerDialog(groups), self._on_group_picked)

    def _on_group_picked(self, group_id: int | None):
        if group_id is not None:
            self._do_launch_group(group_id)

    def _do_launch_group(self, group_id: int):
        groups = self.database.list_groups()
        group = next((g for g in groups if g.id == group_id), None)
        if group:
            sessions = self.manager.launch_group(group)
            self._set_status(f"Launched group '{group.name}' ({len(sessions)} terminals)")
            self._refresh_table()

    def action_inject(self):
        table = self.query_one("#session-table", SessionTable)
        pid = table.get_selected_pid()
        if pid is not None:
            session = self.manager.sessions.get(pid)
            if session and session.status == SessionStatus.ALIVE:
                self.push_screen(
                    InjectDialog(session_label=session.label or str(pid)),
                    lambda text: self._do_inject(pid, text),
                )
            else:
                self._set_status("Session is not alive")

    def _do_inject(self, pid: int, text: str | None):
        if text:
            success = self.manager.inject_text(pid, text)
            if success:
                self._set_status(f"Injected into PID {pid}")
            else:
                self._set_status(f"Injection failed for PID {pid}")

    def action_capture_layout(self):
        layout = self.manager.capture_layout(f"layout_{datetime.now():%Y%m%d_%H%M}")
        if layout:
            self._set_status(f"Captured layout: {layout.name}")

    def action_refresh(self):
        self._refresh_table()
        self._refresh_sidebar()
        self._set_status("Refreshed")

    # -- Config Export/Import --

    def export_config(self, path: Path):
        """Export favorites, groups, and layouts to a JSON file."""
        data = {
            "favorites": [
                {
                    "label": f.label,
                    "shell_type": f.shell_type.value,
                    "working_dir": f.working_dir,
                    "startup_commands": f.startup_commands,
                }
                for f in self.database.list_favorites()
            ],
            "groups": [],
        }
        for g in self.database.list_groups():
            group_favs = self.database.get_group_favorites(g.id)
            data["groups"].append({
                "name": g.name,
                "favorite_labels": [f.label for f in group_favs],
            })
        path.write_text(json.dumps(data, indent=2))
        self._set_status(f"Exported config to {path}")

    def import_config(self, path: Path):
        """Import favorites and groups from a JSON file (merge semantics)."""
        data = json.loads(path.read_text())
        from .models import ShellType
        for fav_data in data.get("favorites", []):
            fav = Favorite(
                label=fav_data["label"],
                shell_type=ShellType(fav_data["shell_type"]),
                working_dir=fav_data.get("working_dir", ""),
                startup_commands=fav_data.get("startup_commands", []),
            )
            self.database.upsert_favorite(fav)
        # Import groups and link by favorite label
        all_favs = self.database.list_favorites()
        label_to_id = {f.label: f.id for f in all_favs}
        from .models import Group
        for grp_data in data.get("groups", []):
            group = Group(name=grp_data["name"])
            group = self.database.upsert_group(group)
            fav_ids = [
                label_to_id[lbl]
                for lbl in grp_data.get("favorite_labels", [])
                if lbl in label_to_id
            ]
            if fav_ids:
                self.database.set_group_favorites(group.id, fav_ids)
        self._refresh_sidebar()
        self._set_status(f"Imported config from {path}")

    # -- Widget Messages --

    def on_group_browser_favorite_selected(self, event: GroupBrowser.FavoriteSelected):
        favs = self.database.list_favorites()
        fav = next((f for f in favs if f.id == event.favorite_id), None)
        if fav:
            session = self.manager.spawn_from_favorite(fav)
            self._set_status(f"Launched '{fav.label}' (PID {session.pid})")
            self._refresh_table()

    def on_group_browser_group_selected(self, event: GroupBrowser.GroupSelected):
        self._do_launch_group(event.group_id)

    def on_unmount(self):
        if self._poll_timer:
            self._poll_timer.stop()
        if self._analysis_timer:
            self._analysis_timer.stop()
        self.database.close()
