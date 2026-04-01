"""Auto-detect platform and export the appropriate terminal driver."""

from __future__ import annotations

import sys

from .base import TerminalDriver


def get_driver() -> TerminalDriver:
    """Return a TerminalDriver for the current platform."""
    if sys.platform == "win32":
        from .windows import WindowsDriver
        return WindowsDriver()
    elif sys.platform == "darwin":
        from .macos import MacOSDriver
        return MacOSDriver()
    else:
        from .linux import LinuxDriver
        return LinuxDriver()


__all__ = ["TerminalDriver", "get_driver"]
