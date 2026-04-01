"""Context-aware command palette provider for TermDash."""

from __future__ import annotations

from textual.command import Provider, Hit, DiscoveryHit, Hits
from textual.widgets import Input, ListView

from .widgets import SessionTable


# Commands grouped by context: (label, action_name, help_text)
_SESSION_COMMANDS = [
    ("Kill Session", "kill", "Ctrl+K — Kill the selected session"),
    ("Focus Terminal Window", "focus_term", "Ctrl+F — Bring terminal to foreground"),
    ("Save as Favorite", "save_favorite", "Ctrl+S — Save session as favorite"),
    ("Inject Text", "inject", "Ctrl+I — Send text to terminal"),
    ("Capture Layout", "capture_layout", "Ctrl+L — Snapshot window positions"),
]

_SIDEBAR_COMMANDS = [
    ("Delete Favorite", "delete_favorite", "Ctrl+D — Delete selected favorite"),
    ("Add to Group", "add_to_group", "Ctrl+A — Add favorite to a group"),
    ("Create Group", "create_group", "Ctrl+T — Create a new group"),
    ("Launch Group", "launch_group", "Ctrl+G — Launch all terminals in a group"),
]

_FILTER_COMMANDS = [
    ("Back to Table", "unfocus_filter", "Esc — Return focus to session table"),
]

_GLOBAL_COMMANDS = [
    ("New Terminal", "spawn", "Ctrl+N — Spawn a new terminal"),
    ("Launch Group", "launch_group", "Ctrl+G — Launch a group"),
    ("Filter Sessions", "filter", "/ — Focus the filter input"),
    ("Refresh", "refresh", "Ctrl+R — Refresh sessions and sidebar"),
    ("Quit", "quit", "Ctrl+Q — Exit TermDash"),
]


def _is_in_sidebar(widget) -> bool:
    """Check if a widget is inside the GroupBrowser sidebar."""
    node = widget
    while node is not None:
        if hasattr(node, "id") and node.id == "sidebar":
            return True
        node = getattr(node, "parent", None)
    return False


class TermDashCommands(Provider):
    """Context-aware commands that adapt to the focused panel."""

    async def discover(self) -> Hits:
        focused = self.focused
        if isinstance(focused, SessionTable):
            for label, action, help_text in _SESSION_COMMANDS[:3]:
                yield DiscoveryHit(label, help=help_text)
        elif _is_in_sidebar(focused):
            for label, action, help_text in _SIDEBAR_COMMANDS[:3]:
                yield DiscoveryHit(label, help=help_text)
        else:
            for label, action, help_text in _GLOBAL_COMMANDS[:3]:
                yield DiscoveryHit(label, help=help_text)

    async def search(self, query: str) -> Hits:
        matcher = self.matcher(query)
        focused = self.focused

        # Build context-specific commands + global commands
        commands = list(_GLOBAL_COMMANDS)
        if isinstance(focused, SessionTable):
            commands = _SESSION_COMMANDS + commands
        elif isinstance(focused, Input) and getattr(focused, "id", "") == "filter-input":
            commands = _FILTER_COMMANDS + commands
        elif _is_in_sidebar(focused):
            commands = _SIDEBAR_COMMANDS + commands

        for label, action, help_text in commands:
            score = matcher.match(label)
            if score > 0:
                yield Hit(
                    score,
                    matcher.highlight(label),
                    self.app.action_to_callable(f"action_{action}"),
                    help=help_text,
                )
