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


def _is_our_hook_command(command: str) -> bool:
    """True if `command` invokes loom_hook.py, wherever it lives.

    Matched by the script argument's basename, not the full command string --
    so a repo relocation (different directory, same script filename) is still
    recognised as ours and cleaned up, rather than accumulating a second, dead
    entry forever. An operator's own unrelated hooks never end in this exact
    filename, so this cannot misfire onto them.
    """
    return any(Path(part).name == "loom_hook.py" for part in str(command).split())


def merge(settings: dict, script: str = HOOK_SCRIPT) -> dict:
    """Add Loom's hook command to every event it cares about, once each.

    Pure: takes a dict, returns a dict, touches no filesystem. Safe to call
    with any settings mapping, real or fabricated, in tests or otherwise.

    Self-healing: any existing hook entry that references loom_hook.py under
    a *different* path is treated as stale and dropped before the current
    command is added, so reinstalling after moving the repo replaces the old
    entry instead of appending a second, dead one.

    Tolerant of a hand-edited settings file holding almost anything: an
    event's hooks value that isn't a list, an entry that isn't a dict, or a
    hook item that isn't a dict are all left alone rather than raised on --
    install() must never crash on a file it hasn't even written yet.
    """
    hooks = settings.setdefault("hooks", {})
    for event in STATE_FOR_EVENT:
        entries = hooks.setdefault(event, [])
        if not isinstance(entries, list):
            # Something else owns this shape; don't guess, don't crash.
            continue

        kept_entries = []
        for entry in entries:
            if not isinstance(entry, dict):
                kept_entries.append(entry)
                continue
            inner = entry.get("hooks")
            if not isinstance(inner, list):
                kept_entries.append(entry)
                continue
            kept_items = [
                h for h in inner
                if not (isinstance(h, dict) and _is_our_hook_command(h.get("command", "")))
            ]
            if kept_items:
                kept_entries.append({**entry, "hooks": kept_items})
            # else: this entry held only our own (now-stale) hook -- drop it.

        command = f"python3 {script} {event}"
        kept_entries.append({"hooks": [{"type": "command", "command": command}]})
        hooks[event] = kept_entries
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
