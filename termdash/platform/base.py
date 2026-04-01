"""Abstract base class for platform-specific terminal drivers."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional

from ..models import ShellType, WindowRect


class TerminalDriver(ABC):
    """Interface for spawning and managing native terminal windows."""

    @abstractmethod
    def shell_executable(self, shell_type: ShellType) -> list[str]:
        """Return the command list to launch the given shell type."""

    @abstractmethod
    def spawn(
        self,
        shell_type: ShellType,
        working_dir: str = "",
        startup_commands: list[str] | None = None,
        title: str = "",
    ) -> tuple[int, Optional[int]]:
        """Spawn a new terminal window.

        Returns (pid, window_handle). window_handle may be None on
        platforms that don't expose native handles.
        """

    @abstractmethod
    def is_alive(self, pid: int) -> bool:
        """Check whether a process is still running."""

    @abstractmethod
    def kill(self, pid: int) -> bool:
        """Terminate a process. Returns True on success."""

    @abstractmethod
    def focus_window(self, window_handle: int) -> bool:
        """Bring a terminal window to the foreground."""

    @abstractmethod
    def get_window_rect(self, window_handle: int) -> Optional[WindowRect]:
        """Get the position and size of a window."""

    @abstractmethod
    def set_window_rect(self, window_handle: int, rect: WindowRect) -> bool:
        """Move/resize a window to the given rect."""

    @abstractmethod
    def get_window_title(self, window_handle: int) -> str:
        """Read the title bar text of a window."""

    @abstractmethod
    def find_window_for_pid(self, pid: int) -> Optional[int]:
        """Find the window handle associated with a PID."""

    @abstractmethod
    def get_screen_size(self) -> tuple[int, int]:
        """Return (width, height) of the primary monitor."""

    def minimize_window(self, window_handle: int) -> bool:
        """Minimize a window. Optional — defaults to no-op."""
        return False

    def restore_window(self, window_handle: int) -> bool:
        """Restore a minimized window. Optional — defaults to no-op."""
        return False

    def inject_text(self, window_handle: int, text: str) -> bool:
        """Send text/keystrokes to a terminal window. Optional — defaults to no-op."""
        return False

    def read_screen(self, window_handle: int, pid: int, lines: int = 50) -> str | None:
        """Read visible text from a terminal window. Optional — defaults to None."""
        return None
