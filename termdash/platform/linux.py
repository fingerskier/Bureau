"""Linux terminal driver — stub for Phase 5 implementation."""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path
from typing import Optional

import psutil

from ..models import ShellType, WindowRect
from .base import TerminalDriver


class LinuxDriver(TerminalDriver):
    """Basic Linux driver using subprocess and xdotool/wmctrl when available."""

    _log_dir: Path = Path(tempfile.gettempdir()) / "termdash_logs"
    _pid_logs: dict[int, Path] = {}  # pid -> log file path

    SHELL_MAP: dict[ShellType, list[str]] = {
        ShellType.BASH: ["/bin/bash"],
        ShellType.ZSH: ["/bin/zsh"],
    }

    def shell_executable(self, shell_type: ShellType) -> list[str]:
        return self.SHELL_MAP.get(shell_type, ["/bin/bash"])

    def spawn(
        self,
        shell_type: ShellType,
        working_dir: str = "",
        startup_commands: list[str] | None = None,
        title: str = "",
    ) -> tuple[int, Optional[int]]:
        self._log_dir.mkdir(parents=True, exist_ok=True)

        terminal_cmds = [
            ["gnome-terminal", "--"],
            ["konsole", "-e"],
            ["xterm", "-e"],
        ]

        shell = self.shell_executable(shell_type)
        cwd = working_dir or None

        # Create a log file for output capture
        log_file = self._log_dir / f"termdash_{id(self)}_{len(self._pid_logs)}.log"
        log_file.touch()

        # Wrap shell command in `script` for output capture
        if startup_commands:
            chain = " && ".join(startup_commands)
            script_cmd = shell + ["-c", f"{chain} ; exec $SHELL"]
        else:
            script_cmd = shell

        wrapped = ["script", "-qf", str(log_file)] + script_cmd

        for term_cmd in terminal_cmds:
            try:
                cmd = term_cmd + wrapped
                proc = subprocess.Popen(cmd, cwd=cwd)
                self._pid_logs[proc.pid] = log_file
                return proc.pid, None
            except FileNotFoundError:
                continue

        # Fallback: bare shell with script wrapper
        proc = subprocess.Popen(wrapped, cwd=cwd)
        self._pid_logs[proc.pid] = log_file
        return proc.pid, None

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
        except Exception:
            try:
                psutil.Process(pid).kill()
                return True
            except Exception:
                return False

    def focus_window(self, window_handle: int) -> bool:
        try:
            subprocess.run(["xdotool", "windowactivate", str(window_handle)],
                           capture_output=True, timeout=2)
            return True
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return False

    def get_window_rect(self, window_handle: int) -> Optional[WindowRect]:
        try:
            result = subprocess.run(
                ["xdotool", "getwindowgeometry", "--shell", str(window_handle)],
                capture_output=True, text=True, timeout=2,
            )
            vals = {}
            for line in result.stdout.strip().splitlines():
                k, v = line.split("=")
                vals[k] = int(v)

            size = subprocess.run(
                ["xdotool", "getwindowfocus", "getwindowgeometry", "--shell"],
                capture_output=True, text=True, timeout=2,
            )
            # xdotool gives X, Y, WIDTH, HEIGHT
            return WindowRect(
                x=vals.get("X", 0), y=vals.get("Y", 0),
                width=vals.get("WIDTH", 800), height=vals.get("HEIGHT", 600),
            )
        except (FileNotFoundError, subprocess.TimeoutExpired, ValueError):
            return None

    def set_window_rect(self, window_handle: int, rect: WindowRect) -> bool:
        try:
            subprocess.run([
                "xdotool", "windowmove", str(window_handle), str(rect.x), str(rect.y),
            ], capture_output=True, timeout=2)
            subprocess.run([
                "xdotool", "windowsize", str(window_handle), str(rect.width), str(rect.height),
            ], capture_output=True, timeout=2)
            return True
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return False

    def get_window_title(self, window_handle: int) -> str:
        try:
            result = subprocess.run(
                ["xdotool", "getwindowname", str(window_handle)],
                capture_output=True, text=True, timeout=2,
            )
            return result.stdout.strip()
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return ""

    def find_window_for_pid(self, pid: int) -> Optional[int]:
        try:
            result = subprocess.run(
                ["xdotool", "search", "--pid", str(pid)],
                capture_output=True, text=True, timeout=2,
            )
            lines = result.stdout.strip().splitlines()
            return int(lines[0]) if lines else None
        except (FileNotFoundError, subprocess.TimeoutExpired, ValueError):
            return None

    def get_screen_size(self) -> tuple[int, int]:
        try:
            result = subprocess.run(
                ["xdpyinfo"],
                capture_output=True, text=True, timeout=2,
            )
            for line in result.stdout.splitlines():
                if "dimensions:" in line:
                    # "  dimensions:    1920x1080 pixels"
                    parts = line.split()[1].split("x")
                    return int(parts[0]), int(parts[1])
        except (FileNotFoundError, subprocess.TimeoutExpired, ValueError):
            pass
        return 1920, 1080

    def inject_text(self, window_handle: int, text: str) -> bool:
        """Send keystrokes to a terminal window via xdotool."""
        try:
            self.focus_window(window_handle)
            subprocess.run(
                ["xdotool", "type", "--window", str(window_handle), "--clearmodifiers", text],
                capture_output=True, timeout=5,
            )
            subprocess.run(
                ["xdotool", "key", "--window", str(window_handle), "Return"],
                capture_output=True, timeout=2,
            )
            return True
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return False

    def read_screen(self, window_handle: int, pid: int, lines: int = 50) -> str | None:
        """Read terminal output from script log file."""
        log_file = self._pid_logs.get(pid)
        if not log_file or not log_file.exists():
            return None
        try:
            # Read last N lines from the log file
            content = log_file.read_text(errors="replace")
            all_lines = content.splitlines()
            return "\n".join(all_lines[-lines:])
        except Exception:
            return None
