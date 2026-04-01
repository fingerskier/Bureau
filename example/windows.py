"""Windows terminal driver using win32gui and subprocess."""

from __future__ import annotations

import os
import subprocess
import time
from typing import Optional

import psutil

from ..models import ShellType, WindowRect
from .base import TerminalDriver

# Lazy imports for win32 — only available on Windows
_win32 = None


def _ensure_win32():
    global _win32
    if _win32 is None:
        import ctypes
        import win32con
        import win32gui
        import win32process
        _win32 = type("Win32", (), {
            "gui": win32gui,
            "process": win32process,
            "con": win32con,
            "ctypes": ctypes,
        })()
    return _win32


class WindowsDriver(TerminalDriver):

    SHELL_MAP: dict[ShellType, list[str]] = {
        ShellType.POWERSHELL: ["powershell.exe"],
        ShellType.PWSH: ["pwsh.exe"],
        ShellType.CMD: ["cmd.exe"],
        ShellType.WSL: ["wsl.exe"],
        ShellType.GIT_BASH: [r"C:\Program Files\Git\bin\bash.exe", "--login", "-i"],
    }

    def shell_executable(self, shell_type: ShellType) -> list[str]:
        return self.SHELL_MAP.get(shell_type, ["powershell.exe"])

    def spawn(
        self,
        shell_type: ShellType,
        working_dir: str = "",
        startup_commands: list[str] | None = None,
        title: str = "",
    ) -> tuple[int, Optional[int]]:
        cmd = list(self.shell_executable(shell_type))
        cwd = working_dir or None

        # Inject startup commands via shell-specific mechanisms
        if startup_commands:
            chain = " && ".join(startup_commands)
            if shell_type in (ShellType.POWERSHELL, ShellType.PWSH):
                # -NoExit keeps the window open after commands run
                cmd += ["-NoExit", "-Command", chain]
            elif shell_type == ShellType.CMD:
                cmd = ["cmd.exe", "/K", chain]
            elif shell_type in (ShellType.WSL, ShellType.GIT_BASH, ShellType.BASH, ShellType.ZSH):
                cmd += ["-c", f"{chain} ; exec $SHELL"]

        # Set window title via environment
        env = os.environ.copy()
        if title:
            env["TERMDASH_TITLE"] = title

        proc = subprocess.Popen(
            cmd,
            cwd=cwd,
            env=env,
            creationflags=subprocess.CREATE_NEW_CONSOLE,
        )

        # Give the window a moment to appear, then find its handle
        time.sleep(0.3)
        hwnd = self.find_window_for_pid(proc.pid)

        # Set the window title if we got a handle
        if hwnd and title:
            w = _ensure_win32()
            w.gui.SetWindowText(hwnd, title)

        return proc.pid, hwnd

    def is_alive(self, pid: int) -> bool:
        try:
            p = psutil.Process(pid)
            return p.is_running() and p.status() != psutil.STATUS_ZOMBIE
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            return False

    def kill(self, pid: int) -> bool:
        try:
            p = psutil.Process(pid)
            p.terminate()
            p.wait(timeout=3)
            return True
        except (psutil.NoSuchProcess, psutil.TimeoutExpired, psutil.AccessDenied):
            try:
                p.kill()
                return True
            except Exception:
                return False

    def get_window_rect(self, window_handle: int) -> Optional[WindowRect]:
        w = _ensure_win32()
        try:
            left, top, right, bottom = w.gui.GetWindowRect(window_handle)
            placement = w.gui.GetWindowPlacement(window_handle)
            show_cmd = placement[1]
            return WindowRect(
                x=left, y=top,
                width=right - left, height=bottom - top,
                maximized=(show_cmd == w.con.SW_SHOWMAXIMIZED),
                minimized=(show_cmd == w.con.SW_SHOWMINIMIZED),
            )
        except Exception:
            return None

    def set_window_rect(self, window_handle: int, rect: WindowRect) -> bool:
        w = _ensure_win32()
        try:
            if rect.maximized:
                w.gui.ShowWindow(window_handle, w.con.SW_MAXIMIZE)
            elif rect.minimized:
                w.gui.ShowWindow(window_handle, w.con.SW_MINIMIZE)
            else:
                w.gui.ShowWindow(window_handle, w.con.SW_RESTORE)
                w.gui.MoveWindow(window_handle, rect.x, rect.y, rect.width, rect.height, True)
            return True
        except Exception:
            return False

    def focus_window(self, window_handle: int) -> bool:
        w = _ensure_win32()
        try:
            w.gui.ShowWindow(window_handle, w.con.SW_RESTORE)
            w.gui.SetForegroundWindow(window_handle)
            return True
        except Exception:
            return False

    def minimize_window(self, window_handle: int) -> bool:
        w = _ensure_win32()
        try:
            w.gui.ShowWindow(window_handle, w.con.SW_MINIMIZE)
            return True
        except Exception:
            return False

    def restore_window(self, window_handle: int) -> bool:
        w = _ensure_win32()
        try:
            w.gui.ShowWindow(window_handle, w.con.SW_RESTORE)
            return True
        except Exception:
            return False

    def get_window_title(self, window_handle: int) -> str:
        w = _ensure_win32()
        try:
            return w.gui.GetWindowText(window_handle)
        except Exception:
            return ""

    def find_window_for_pid(self, pid: int) -> Optional[int]:
        """Enumerate windows to find one owned by this PID."""
        w = _ensure_win32()
        result = [None]

        def _enum_callback(hwnd, _):
            if not w.gui.IsWindowVisible(hwnd):
                return True
            try:
                _, found_pid = w.process.GetWindowThreadProcessId(hwnd)
                if found_pid == pid:
                    result[0] = hwnd
                    return False  # stop enumeration
            except Exception:
                pass
            return True

        try:
            w.gui.EnumWindows(_enum_callback, None)
        except Exception:
            pass
        return result[0]

    def get_screen_size(self) -> tuple[int, int]:
        w = _ensure_win32()
        return (
            w.ctypes.windll.user32.GetSystemMetrics(0),
            w.ctypes.windll.user32.GetSystemMetrics(1),
        )
