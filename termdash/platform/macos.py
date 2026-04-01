"""macOS terminal driver using osascript and subprocess."""

from __future__ import annotations

import subprocess
import shlex
from typing import Optional

import psutil

from ..models import ShellType, WindowRect
from .base import TerminalDriver


class MacOSDriver(TerminalDriver):

    SHELL_MAP: dict[ShellType, list[str]] = {
        ShellType.BASH: ["/bin/bash"],
        ShellType.ZSH: ["/bin/zsh"],
    }

    def shell_executable(self, shell_type: ShellType) -> list[str]:
        return self.SHELL_MAP.get(shell_type, ["/bin/zsh"])

    def _osascript(self, script: str) -> str:
        """Run AppleScript and return stdout."""
        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True, text=True, timeout=5,
        )
        return result.stdout.strip()

    def spawn(
        self,
        shell_type: ShellType,
        working_dir: str = "",
        startup_commands: list[str] | None = None,
        title: str = "",
    ) -> tuple[int, Optional[int]]:
        # Build the command to execute in the new terminal
        parts = []
        if working_dir:
            parts.append(f"cd {shlex.quote(working_dir)}")
        if startup_commands:
            parts.extend(startup_commands)

        full_cmd = " && ".join(parts) if parts else ""

        if shell_type in (ShellType.TERMINAL, ShellType.ZSH, ShellType.BASH):
            # Use Terminal.app via AppleScript
            if full_cmd:
                script = f'''
                    tell application "Terminal"
                        activate
                        set newTab to do script "{full_cmd}"
                        {"set custom title of newTab to " + shlex.quote(title) if title else ""}
                    end tell
                '''
            else:
                script = '''
                    tell application "Terminal"
                        activate
                        do script ""
                    end tell
                '''
            self._osascript(script)

            # Get the PID of the most recent Terminal process
            pid = self._get_latest_terminal_pid()
            return pid or 0, None

        elif shell_type == ShellType.ITERM:
            cmd_str = full_cmd or ""
            script = f'''
                tell application "iTerm"
                    activate
                    tell current window
                        create tab with default profile
                        tell current session
                            write text "{cmd_str}"
                        end tell
                    end tell
                end tell
            '''
            self._osascript(script)
            pid = self._get_latest_terminal_pid("iTerm2")
            return pid or 0, None

        else:
            # Fallback: just launch the shell directly (no native window management)
            cmd = list(self.shell_executable(shell_type))
            proc = subprocess.Popen(cmd, cwd=working_dir or None)
            return proc.pid, None

    def _get_latest_terminal_pid(self, app_name: str = "Terminal") -> Optional[int]:
        """Find the PID of the most recently spawned Terminal/iTerm process."""
        for proc in psutil.process_iter(["name", "create_time"]):
            try:
                if app_name.lower() in proc.info["name"].lower():
                    return proc.pid
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        return None

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

    def get_window_rect(self, window_handle: int) -> Optional[WindowRect]:
        # macOS window management via AppleScript is limited;
        # window_handle isn't used the same way as Windows HWND.
        # Would need accessibility APIs (pyobjc) for full support.
        return None

    def set_window_rect(self, window_handle: int, rect: WindowRect) -> bool:
        # Future: use Terminal.app AppleScript window positioning
        # tell application "Terminal" to set bounds of front window to {x, y, x+w, y+h}
        return False

    def focus_window(self, window_handle: int) -> bool:
        self._osascript('tell application "Terminal" to activate')
        return True

    def get_window_title(self, window_handle: int) -> str:
        return self._osascript(
            'tell application "Terminal" to get name of front window'
        )

    def find_window_for_pid(self, pid: int) -> Optional[int]:
        # macOS doesn't map PIDs to window handles the same way
        return None

    def get_screen_size(self) -> tuple[int, int]:
        result = self._osascript(
            'tell application "Finder" to get bounds of window of desktop'
        )
        try:
            parts = [int(x.strip()) for x in result.split(",")]
            return parts[2], parts[3]
        except Exception:
            return 1920, 1080

    def inject_text(self, window_handle: int, text: str) -> bool:
        """Send keystrokes to Terminal.app via AppleScript."""
        escaped = text.replace("\\", "\\\\").replace('"', '\\"')
        script = f'''
            tell application "Terminal"
                activate
                tell front window
                    do script "{escaped}" in selected tab
                end tell
            end tell
        '''
        try:
            self._osascript(script)
            return True
        except Exception:
            return False

    def read_screen(self, window_handle: int, pid: int, lines: int = 50) -> str | None:
        """Read Terminal.app window content via AppleScript."""
        try:
            content = self._osascript(
                'tell application "Terminal" to get contents of selected tab of front window'
            )
            if not content:
                return None
            # Return last N lines
            all_lines = content.splitlines()
            return "\n".join(all_lines[-lines:])
        except Exception:
            return None
