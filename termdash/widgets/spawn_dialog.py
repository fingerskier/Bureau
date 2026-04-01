"""Dialog screens for TermDash."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Input, Label, OptionList
from textual.widgets.option_list import Option

from ..models import Favorite, Group, ShellType


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


class GroupPickerDialog(ModalScreen[int | None]):
    """Pick a group to launch."""

    BINDINGS = [Binding("escape", "cancel", "Cancel")]

    CSS = """
    GroupPickerDialog { align: center middle; }
    #group-picker {
        width: 50; height: auto; max-height: 20;
        border: thick $accent; background: $surface; padding: 1 2;
    }
    """

    def __init__(self, groups: list[Group]):
        super().__init__()
        self.groups = groups

    def compose(self) -> ComposeResult:
        with Vertical(id="group-picker"):
            yield Label("Launch Group")
            yield OptionList(
                *[Option(g.name, id=str(g.id)) for g in self.groups],
                id="group-select",
            )

    def on_option_list_option_selected(self, event: OptionList.OptionSelected):
        self.dismiss(int(event.option.id))

    def action_cancel(self):
        self.dismiss(None)


class InjectDialog(ModalScreen[str | None]):
    """Prompt for text to inject into a running terminal."""

    BINDINGS = [Binding("escape", "cancel", "Cancel")]

    CSS = """
    InjectDialog { align: center middle; }
    #inject-dialog {
        width: 60; height: auto; border: thick $warning;
        background: $surface; padding: 1 2;
    }
    """

    def __init__(self, session_label: str = ""):
        super().__init__()
        self.session_label = session_label

    def compose(self) -> ComposeResult:
        with Vertical(id="inject-dialog"):
            yield Label(f"Inject into: {self.session_label}")
            yield Label("Command:")
            yield Input(placeholder="e.g. ls -la", id="inject-input")

    def on_input_submitted(self, event: Input.Submitted):
        self.dismiss(event.value or None)

    def action_cancel(self):
        self.dismiss(None)
