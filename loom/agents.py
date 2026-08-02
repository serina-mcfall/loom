"""What each agent is doing. Hooks are the truth; liveness is the honest fallback."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .runner import Runner

TMUX_FORMAT = "#{pane_current_path}\t#{pane_current_command}\t#{pane_pid}\t#{window_name}"
ACTIVE_STATES = {"working", "waiting", "idle"}
AGENT_COMMANDS = {"claude", "node"}

DEFAULT_STATE_DIR = os.path.expanduser("~/.loom/state")


@dataclass
class AgentState:
    state: str = "none"
    source: str = "none"
    since: str | None = None
    pid: int | None = None
    tmux_window: str | None = None


def pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except (ProcessLookupError, ValueError):
        return False
    except PermissionError:
        return True
    return True


def read_state_dir(state_dir: str) -> list[dict]:
    d = Path(state_dir)
    if not d.is_dir():
        return []
    sessions: list[dict] = []
    for f in sorted(d.glob("*.json")):
        try:
            sessions.append(json.loads(f.read_text()))
        except (json.JSONDecodeError, OSError):
            continue
    return sessions


def tmux_panes(runner: Runner) -> list[dict]:
    r = runner.run(["tmux", "list-panes", "-a", "-F", TMUX_FORMAT], cwd=os.getcwd())
    if not r.ok:
        return []
    panes = []
    for line in r.stdout.splitlines():
        cols = line.split("\t")
        if len(cols) != 4 or not cols[2].isdigit():
            continue
        panes.append({"path": cols[0], "command": cols[1],
                      "pid": int(cols[2]), "window": cols[3]})
    return panes


def agent_for(path: str, sessions: list[dict], panes: list[dict],
              is_alive: Callable[[int], bool] = pid_alive) -> AgentState:
    window = next((p["window"] for p in panes if p["path"] == path), None)

    for s in sessions:
        if s.get("cwd") != path:
            continue
        state = s.get("state", "unknown")
        pid = s.get("pid")
        if state in ACTIVE_STATES and pid is not None and not is_alive(int(pid)):
            state = "stale"
        return AgentState(state, "hook", s.get("since"), pid, window)

    for p in panes:
        if p["path"] == path and p["command"] in AGENT_COMMANDS:
            return AgentState("unknown", "liveness", None, p["pid"], p["window"])

    return AgentState("none", "none", None, None, window)
