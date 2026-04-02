"""Windows terminal driver using win32gui and subprocess."""

from __future__ import annotations

import ctypes
from ctypes import wintypes
import os
import subprocess
import time
from typing import Optional

import psutil

from ..models import ShellType, WindowRect
from .base import TerminalDriver

# Lazy imports for win32 — only available when pywin32 is installed
_win32 = None
_win32_available = True


def _ensure_win32():
    global _win32, _win32_available
    if _win32 is None:
        if not _win32_available:
            return None
        try:
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
        except ImportError:
            _win32_available = False
            return None
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
        w = _ensure_win32()
        if hwnd and title and w:
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
        if not w:
            return None
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
        if not w:
            return False
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
        if not w:
            return False
        try:
            w.gui.ShowWindow(window_handle, w.con.SW_RESTORE)
            w.gui.SetForegroundWindow(window_handle)
            return True
        except Exception:
            return False

    def minimize_window(self, window_handle: int) -> bool:
        w = _ensure_win32()
        if not w:
            return False
        try:
            w.gui.ShowWindow(window_handle, w.con.SW_MINIMIZE)
            return True
        except Exception:
            return False

    def restore_window(self, window_handle: int) -> bool:
        w = _ensure_win32()
        if not w:
            return False
        try:
            w.gui.ShowWindow(window_handle, w.con.SW_RESTORE)
            return True
        except Exception:
            return False

    def get_window_title(self, window_handle: int) -> str:
        """Get window title with timeout to avoid blocking on hung windows."""
        try:
            buf = ctypes.create_unicode_buffer(256)
            SMTO_ABORTIFHUNG = 0x0002
            WM_GETTEXT = 0x000D
            lpdw_result = wintypes.DWORD()
            ret = ctypes.windll.user32.SendMessageTimeoutW(
                window_handle, WM_GETTEXT,
                256, buf,
                SMTO_ABORTIFHUNG, 100,  # 100ms timeout
                ctypes.byref(lpdw_result),
            )
            return buf.value if ret else ""
        except Exception:
            return ""

    def find_window_for_pid(self, pid: int) -> Optional[int]:
        """Enumerate windows to find one owned by this PID."""
        w = _ensure_win32()
        if not w:
            return None
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
        if not w:
            import ctypes
            return (
                ctypes.windll.user32.GetSystemMetrics(0),
                ctypes.windll.user32.GetSystemMetrics(1),
            )
        return (
            w.ctypes.windll.user32.GetSystemMetrics(0),
            w.ctypes.windll.user32.GetSystemMetrics(1),
        )

    def inject_text(self, window_handle: int, text: str) -> bool:
        """Send keystrokes to a terminal window via WM_CHAR messages."""
        w = _ensure_win32()
        if not w:
            return False
        WM_CHAR = 0x0102
        try:
            self.focus_window(window_handle)
            time.sleep(0.1)
            for char in text:
                w.gui.PostMessage(window_handle, WM_CHAR, ord(char), 0)
            w.gui.PostMessage(window_handle, WM_CHAR, ord("\r"), 0)
            return True
        except Exception:
            return False

    def read_screen(self, window_handle: int, pid: int, lines: int = 50) -> str | None:
        """Read the console screen buffer of a terminal process via ctypes."""
        kernel32 = ctypes.windll.kernel32
        STD_OUTPUT_HANDLE = -11

        # Save our own console state, then attach to target
        had_console = kernel32.FreeConsole()
        if not kernel32.AttachConsole(pid):
            # Re-attach to our own console
            if had_console:
                kernel32.AttachConsole(-1)  # ATTACH_PARENT_PROCESS
            return None

        try:
            handle = kernel32.GetStdHandle(STD_OUTPUT_HANDLE)
            if handle == -1:
                return None

            class CONSOLE_SCREEN_BUFFER_INFO(ctypes.Structure):
                _fields_ = [
                    ("dwSize", wintypes._COORD),
                    ("dwCursorPosition", wintypes._COORD),
                    ("wAttributes", wintypes.WORD),
                    ("srWindow", wintypes.SMALL_RECT),
                    ("dwMaximumWindowSize", wintypes._COORD),
                ]

            csbi = CONSOLE_SCREEN_BUFFER_INFO()
            if not kernel32.GetConsoleScreenBufferInfo(handle, ctypes.byref(csbi)):
                return None

            width = csbi.dwSize.X
            # Read from cursor position backwards, up to `lines` lines
            end_row = csbi.dwCursorPosition.Y
            start_row = max(0, end_row - lines + 1)
            total_chars = width * (end_row - start_row + 1)

            buf = ctypes.create_unicode_buffer(total_chars)
            coord = wintypes._COORD(0, start_row)
            chars_read = wintypes.DWORD()
            kernel32.ReadConsoleOutputCharacterW(
                handle, buf, total_chars, coord, ctypes.byref(chars_read)
            )

            # Split into lines and strip trailing whitespace
            raw = buf.value
            result_lines = []
            for i in range(end_row - start_row + 1):
                line = raw[i * width:(i + 1) * width].rstrip()
                result_lines.append(line)

            return "\n".join(result_lines)
        except Exception:
            return None
        finally:
            kernel32.FreeConsole()
            # Re-attach to parent console (Textual manages its own I/O)
            kernel32.AttachConsole(-1)
