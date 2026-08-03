"""Adds Loom's hooks to Claude Code settings without disturbing existing ones.

SAFETY: install() touches an operator's real ~/.claude/settings.json, which can
hold environment variables carrying credentials. merge() is the pure function
that does all the real work — dict in, dict out, no file access — and is what
must be tested. install() itself is a thin, deliberately-untested-against-the-
real-path wrapper: exercise it, if at all, only against a temp file.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from hooks.loom_hook import STATE_FOR_EVENT

SETTINGS = os.path.expanduser("~/.claude/settings.json")
HOOK_SCRIPT = str(Path(__file__).resolve().parent.parent / "hooks" / "loom_hook.py")


def merge(settings: dict, script: str = HOOK_SCRIPT) -> dict:
    """Add Loom's hook command to every event it cares about, once each.

    Pure: takes a dict, returns a dict, touches no filesystem. Safe to call
    with any settings mapping, real or fabricated, in tests or otherwise.
    """
    hooks = settings.setdefault("hooks", {})
    for event in STATE_FOR_EVENT:
        entries = hooks.setdefault(event, [])
        command = f"python3 {script} {event}"
        already = any(
            h.get("command") == command
            for entry in entries for h in entry.get("hooks", []))
        if not already:
            entries.append({"hooks": [{"type": "command", "command": command}]})
    return settings


def install(settings_path: str = SETTINGS) -> int:
    """Write Loom's hooks into settings_path, preserving everything else in it.

    Defaults to the operator's real settings file. NEVER call this in a test
    without pointing settings_path at a temp file — see the module docstring.
    """
    path = Path(settings_path)
    settings = json.loads(path.read_text()) if path.exists() else {}
    path.write_text(json.dumps(merge(settings), indent=2))
    print(f"Loom hooks written to {settings_path}")
    print("Existing sessions keep their old settings — restart an agent to see its state.")
    return 0
