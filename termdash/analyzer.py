"""Claude Haiku terminal analysis via claude CLI."""

from __future__ import annotations

import json
import subprocess
from datetime import datetime

from .models import TerminalAnalysis

_PROMPT = """Analyze this terminal output. Return ONLY valid JSON with these fields:
- state: one of "idle", "working", "error", "blocked"
- waiting_on_user: boolean, true if the terminal is waiting for user input
- summary: string, one-line description of what the terminal is doing
- detected_tool: string or null, the primary tool/process running (e.g. "npm", "python", "gcc")
- suggestions: array of strings, any observations or warnings
- has_errors: boolean, true if error output is visible
- confidence: float 0-1, how confident you are in this analysis"""


def analyze_screen(content: str, timeout: int = 15) -> TerminalAnalysis | None:
    """Send terminal content to Claude Haiku via CLI and parse structured response."""
    if not content or not content.strip():
        return None

    # Truncate to last 50 lines to keep token usage low
    lines = content.splitlines()[-50:]
    truncated = "\n".join(lines)

    try:
        result = subprocess.run(
            ["claude", "-p", "--model", "haiku", _PROMPT],
            input=truncated,
            capture_output=True,
            text=True,
            timeout=timeout,
        )

        if result.returncode != 0:
            return None

        output = result.stdout.strip()

        # Extract JSON from response (handle markdown code fences)
        if "```" in output:
            # Extract content between code fences
            parts = output.split("```")
            for part in parts[1:]:
                # Skip the language identifier line if present
                json_str = part.strip()
                if json_str.startswith("json"):
                    json_str = json_str[4:].strip()
                if json_str.startswith("{"):
                    output = json_str.split("```")[0].strip()
                    break

        data = json.loads(output)

        return TerminalAnalysis(
            state=data.get("state", "unknown"),
            waiting_on_user=bool(data.get("waiting_on_user", False)),
            summary=str(data.get("summary", "")),
            detected_tool=data.get("detected_tool"),
            suggestions=list(data.get("suggestions", [])),
            has_errors=bool(data.get("has_errors", False)),
            confidence=float(data.get("confidence", 0.0)),
            analyzed_at=datetime.now(),
        )
    except (subprocess.TimeoutExpired, FileNotFoundError, json.JSONDecodeError, ValueError):
        return None
