"""TermDash — Textual TUI application."""

from __future__ import annotations

from datetime import datetime
from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.reactive import reactive
from textual.screen import ModalScreen
from textual.timer import Timer
from textual.widgets import (
    DataTable, Footer, Header, Input, Label,
    ListItem, ListView, OptionList, Static,
)
from textual.widgets.option_list import Option

from .db import Database
from .manager import Manager
from .models import Favorite, Group, SessionStatus, ShellType
from .platform import get_driver


# ── Spawn Dialog ──────────────────────────────────────────────

class SpawnDialog(ModalScreen[Favorite | None]):
    """Quick-spawn dialog for a new terminal."""

    BINDINGS = [
        Binding("escape", "cancel", "Cancel"),
    ]

    CSS = """
    SpawnDialog {
        align: center middle;
    }
    #spawn-dialog {
        width: 60;
        height: auto;
        max-height: 24;
        border: thick $accent;
        background: $surface;
        padding: 1 2;
    }
    #spawn-dialog Label {
        margin-bottom: 1;
    }
    #spawn-dialog Input {
        margin-bottom: 1;
    }
    """

    def compose(self) -> ComposeResult:
        shells = ShellType.defaults_for_platform()
        with Vertical(id="spawn-dialog"):
            yield Label("Spawn Terminal", classes="title")
            yield Label("Shell:")
            yield OptionList(
                *[Option(s.value, id=s.value) for s in shells],
                id="shell-select",
            )
            yield Label("Label:")
            yield Input(placeholder="optional label", id="input-label")
            yield Label("Working Directory:")
            yield Input(placeholder="e.g. C:\\Projects\\myapp", id="input-cwd")
            yield Label("Startup Commands (one per line):")
            yield Input(placeholder="e.g. npm run dev", id="input-commands")

    def on_option_list_option_selected(self, event: OptionList.OptionSelected):
        shell = ShellType(event.option.id)
        label = self.query_one("#input-label", Input).value
        cwd = self.query_one("#input-cwd", Input).value
        cmds_raw = self.query_one("#input-commands", Input).value
        commands = [c.strip() for c in cmds_raw.split(";") if c.strip()] if cmds_raw else []

        fav = Favorite(
            label=label or shell.value,
            shell_type=shell,
            working_dir=cwd,
            startup_commands=commands,
        )
        self.dismiss(fav)

    def action_cancel(self):
        self.dismiss(None)


# ── Save Favorite Dialog ─────────────────────────────────────

class SaveFavoriteDialog(ModalScreen[str | None]):
    """Prompt for a name to save current session as a favorite."""

    BINDINGS = [Binding("escape", "cancel", "Cancel")]

    CSS = """
    SaveFavoriteDialog { align: center middle; }
    #save-fav-dialog {
        width: 50; height: auto; border: thick $accent;
        background: $surface; padding: 1 2;
    }
    """

    def compose(self) -> ComposeResult:
        with Vertical(id="save-fav-dialog"):
            yield Label("Save as Favorite")
            yield Label("Label:")
            yield Input(placeholder="My Dev Terminal", id="fav-name")

    def on_input_submitted(self, event: Input.Submitted):
        self.dismiss(event.value or None)

    def action_cancel(self):
        self.dismiss(None)


# ── Main App ─────────────────────────────────────────────────

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
    """

    BINDINGS = [
        Binding("n", "spawn", "New Terminal"),
        Binding("k", "kill", "Kill Selected"),
        Binding("f", "focus_term", "Focus Window"),
        Binding("s", "save_favorite", "Save Favorite"),
        Binding("g", "launch_group", "Launch Group"),
        Binding("c", "capture_layout", "Capture Layout"),
        Binding("r", "refresh", "Refresh"),
        Binding("q", "quit", "Quit"),
    ]

    session_count: reactive[int] = reactive(0)

    def __init__(self):
        super().__init__()
        self.db = Database()
        self.driver = get_driver()
        self.manager = Manager(self.db, self.driver)
        self._poll_timer: Timer | None = None

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal(id="main"):
            with Vertical(id="sessions-panel"):
                yield Label("Sessions", classes="section-title")
                yield DataTable(id="session-table")
            with Vertical(id="sidebar"):
                yield Label("Favorites", classes="section-title")
                yield ListView(id="fav-list")
                yield Label("Groups", classes="section-title")
                yield ListView(id="group-list")
        yield Static("Ready", id="status-bar")
        yield Footer()

    def on_mount(self):
        # Set up session table columns
        table = self.query_one("#session-table", DataTable)
        table.add_columns("PID", "Label", "Shell", "Dir", "Uptime", "Mem", "Status")
        table.cursor_type = "row"

        # Reconnect previous sessions
        reconnected = self.manager.reconnect()
        self._set_status(f"Reconnected {reconnected} session(s)")

        # Load favorites & groups into sidebar
        self._refresh_sidebar()

        # Start polling
        self._poll_timer = self.set_interval(2.0, self._poll_sessions)
        self._refresh_table()

    def _set_status(self, msg: str):
        self.query_one("#status-bar", Static).update(msg)

    # ── Table ──

    def _refresh_table(self):
        table = self.query_one("#session-table", DataTable)
        table.clear()
        self.manager.refresh_all()

        for session in self.manager.get_all_sessions():
            uptime = ""
            if session.spawned_at:
                delta = datetime.now() - session.spawned_at
                mins = int(delta.total_seconds() // 60)
                uptime = f"{mins}m"

            status_icon = "●" if session.status == SessionStatus.ALIVE else "○"
            table.add_row(
                str(session.pid),
                session.label or "—",
                session.shell_type.value,
                _truncate(session.working_dir, 25),
                uptime,
                f"{session.memory_mb:.0f}MB" if session.memory_mb else "—",
                status_icon,
                key=str(session.pid),
            )

        self.session_count = len(self.manager.get_live_sessions())

    def _poll_sessions(self):
        self._refresh_table()

    # ── Sidebar ──

    def _refresh_sidebar(self):
        fav_list = self.query_one("#fav-list", ListView)
        fav_list.clear()
        for fav in self.db.list_favorites():
            fav_list.append(ListItem(Label(f"⭐ {fav.label}"), id=f"fav-{fav.id}"))

        group_list = self.query_one("#group-list", ListView)
        group_list.clear()
        for group in self.db.list_groups():
            group_list.append(ListItem(Label(f"📁 {group.name}"), id=f"grp-{group.id}"))

    # ── Actions ──

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
                # Re-spawn properly with commands
                self.manager.kill_session(session.pid)
                session = self.manager.spawn_from_favorite(result)
            self._set_status(f"Spawned {result.label} (PID {session.pid})")
            self._refresh_table()

    def action_kill(self):
        table = self.query_one("#session-table", DataTable)
        if table.cursor_row is not None:
            row_key = table.get_row_at(table.cursor_row)
            pid = int(row_key[0])
            self.manager.kill_session(pid)
            self._set_status(f"Killed PID {pid}")
            self._refresh_table()

    def action_focus_term(self):
        table = self.query_one("#session-table", DataTable)
        if table.cursor_row is not None:
            row_key = table.get_row_at(table.cursor_row)
            pid = int(row_key[0])
            self.manager.focus_session(pid)

    def action_save_favorite(self):
        table = self.query_one("#session-table", DataTable)
        if table.cursor_row is not None:
            row = table.get_row_at(table.cursor_row)
            pid = int(row[0])
            session = self.manager.sessions.get(pid)
            if session:
                self.push_screen(
                    SaveFavoriteDialog(),
                    lambda name: self._do_save_favorite(session, name),
                )

    def _do_save_favorite(self, session, name: str | None):
        if name:
            fav = Favorite(
                label=name,
                shell_type=session.shell_type,
                working_dir=session.working_dir,
            )
            self.db.upsert_favorite(fav)
            self._set_status(f"Saved favorite: {name}")
            self._refresh_sidebar()

    def action_launch_group(self):
        groups = self.db.list_groups()
        if not groups:
            self._set_status("No groups defined yet")
            return
        # Launch the first group for now — TODO: group picker
        group = groups[0]
        sessions = self.manager.launch_group(group)
        self._set_status(f"Launched group '{group.name}' ({len(sessions)} terminals)")
        self._refresh_table()

    def action_capture_layout(self):
        layout = self.manager.capture_layout(f"layout_{datetime.now():%Y%m%d_%H%M}")
        if layout:
            self._set_status(f"Captured layout: {layout.name}")

    def action_refresh(self):
        self._refresh_table()
        self._refresh_sidebar()
        self._set_status("Refreshed")

    # ── Sidebar Events ──

    def on_list_view_selected(self, event: ListView.Selected):
        item_id = event.item.id or ""
        if item_id.startswith("fav-"):
            fav_id = int(item_id.split("-")[1])
            favs = self.db.list_favorites()
            fav = next((f for f in favs if f.id == fav_id), None)
            if fav:
                session = self.manager.spawn_from_favorite(fav)
                self._set_status(f"Launched '{fav.label}' (PID {session.pid})")
                self._refresh_table()
        elif item_id.startswith("grp-"):
            group_id = int(item_id.split("-")[1])
            groups = self.db.list_groups()
            group = next((g for g in groups if g.id == group_id), None)
            if group:
                sessions = self.manager.launch_group(group)
                self._set_status(f"Launched group '{group.name}'")
                self._refresh_table()

    def on_unmount(self):
        if self._poll_timer:
            self._poll_timer.stop()
        self.db.close()


def _truncate(s: str, max_len: int) -> str:
    return s if len(s) <= max_len else "…" + s[-(max_len - 1):]
