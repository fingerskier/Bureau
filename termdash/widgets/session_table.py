"""Live session table widget."""

from __future__ import annotations

from datetime import datetime

from textual.widgets import DataTable

from ..models import ActivityState, Session, SessionStatus


# Activity indicators (terminal-safe characters)
_ACTIVITY_ICONS = {
    ActivityState.WORKING: "[bold green]>>>[/]",   # active work
    ActivityState.WAITING: "[yellow]...[/]",        # waiting for input
    ActivityState.IDLE:    "[dim]zzz[/]",           # idle
    ActivityState.UNKNOWN: "[dim]?[/]",
}


class SessionTable(DataTable):
    """DataTable showing tracked terminal sessions with live status."""

    def on_mount(self):
        self.add_columns("PID", "Label", "Shell", "Dir", "Title", "Uptime", "Mem", "Activity")
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
            else:
                activity = _ACTIVITY_ICONS.get(session.activity, "?")

            self.add_row(
                str(session.pid),
                session.label or "\u2014",
                session.shell_type.value,
                _truncate(session.working_dir, 20),
                _truncate(session.window_title, 25) if session.window_title else "\u2014",
                uptime,
                f"{session.memory_mb:.0f}MB" if session.memory_mb else "\u2014",
                activity,
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
