"""Data models for TermDash."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional


class ShellType(str, Enum):
    POWERSHELL = "powershell"
    PWSH = "pwsh"
    CMD = "cmd"
    WSL = "wsl"
    GIT_BASH = "git_bash"
    BASH = "bash"
    ZSH = "zsh"
    TERMINAL = "terminal"  # macOS Terminal.app
    ITERM = "iterm"        # macOS iTerm2

    @classmethod
    def defaults_for_platform(cls) -> list[ShellType]:
        import sys
        if sys.platform == "win32":
            return [cls.POWERSHELL, cls.PWSH, cls.CMD, cls.WSL, cls.GIT_BASH]
        elif sys.platform == "darwin":
            return [cls.ZSH, cls.BASH, cls.TERMINAL, cls.ITERM]
        return [cls.BASH, cls.ZSH]


class SessionStatus(str, Enum):
    ALIVE = "alive"
    DEAD = "dead"
    UNKNOWN = "unknown"


class ActivityState(str, Enum):
    """Inferred activity level based on CPU usage patterns."""
    WORKING = "working"    # sustained CPU activity
    WAITING = "waiting"    # process alive but blocked on input
    IDLE = "idle"          # negligible CPU for multiple polls
    UNKNOWN = "unknown"


@dataclass
class TerminalAnalysis:
    """Structured output from Claude Haiku terminal analysis."""
    state: str = "unknown"           # idle|working|error|blocked
    waiting_on_user: bool = False
    summary: str = ""
    detected_tool: str | None = None
    suggestions: list[str] = field(default_factory=list)
    has_errors: bool = False
    confidence: float = 0.0
    analyzed_at: Optional[datetime] = None


@dataclass
class Favorite:
    id: Optional[int] = None
    label: str = ""
    shell_type: ShellType = ShellType.POWERSHELL
    working_dir: str = ""
    startup_commands: list[str] = field(default_factory=list)
    created_at: Optional[datetime] = None

    def commands_json(self) -> str:
        return json.dumps(self.startup_commands)

    @staticmethod
    def commands_from_json(raw: str) -> list[str]:
        return json.loads(raw) if raw else []


@dataclass
class Group:
    id: Optional[int] = None
    name: str = ""
    layout_id: Optional[int] = None
    created_at: Optional[datetime] = None


@dataclass
class GroupFavorite:
    group_id: int = 0
    favorite_id: int = 0
    sort_order: int = 0


@dataclass
class WindowRect:
    x: int = 0
    y: int = 0
    width: int = 800
    height: int = 600
    maximized: bool = False
    minimized: bool = False


@dataclass
class Layout:
    id: Optional[int] = None
    name: str = ""
    monitor_width: int = 1920
    monitor_height: int = 1080
    created_at: Optional[datetime] = None


@dataclass
class LayoutWindow:
    layout_id: int = 0
    favorite_id: int = 0
    rect: WindowRect = field(default_factory=WindowRect)


@dataclass
class Session:
    id: Optional[int] = None
    pid: int = 0
    window_handle: Optional[int] = None
    favorite_id: Optional[int] = None
    group_id: Optional[int] = None
    label: str = ""
    shell_type: ShellType = ShellType.POWERSHELL
    working_dir: str = ""
    spawned_at: Optional[datetime] = None
    status: SessionStatus = SessionStatus.ALIVE
    # runtime-only fields (not persisted)
    cpu_percent: float = 0.0
    memory_mb: float = 0.0
    window_title: str = ""
    activity: ActivityState = ActivityState.UNKNOWN
    _cpu_history: list[float] = field(default_factory=list, repr=False)
    screen_content: str = ""
    visually_idle: bool = False
    analysis: Optional[TerminalAnalysis] = None
    _screen_hash: str = field(default="", repr=False)
    _screen_idle_count: int = field(default=0, repr=False)
