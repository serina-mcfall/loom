"""What each agent is doing. Hooks say what; the process list says whether it exists."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

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
    # Informational only — never a liveness signal. A Claude Code command hook
    # runs under `sh -c`, so the pid recorded at hook time is that transient
    # shell wrapper's parent, which is long gone by the time anything reads it.
    pid: int | None = None
    tmux_window: str | None = None


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


def _pane_in_worktree(pane_path: str, norm_path: str) -> bool:
    p = os.path.realpath(pane_path)
    return p == norm_path or p.startswith(norm_path + os.sep)


def agent_for(path: str, sessions: list[dict], panes: list[dict]) -> AgentState:
    window = next((p["window"] for p in panes if p["path"] == path), None)

    norm_path = os.path.realpath(path)
    state_priority = {"waiting": 0, "working": 1, "idle": 2, "stale": 3, "stopped": 4}

    # Collect all sessions whose cwd is the worktree or inside it
    matching_sessions = []
    for s in sessions:
        s_cwd = os.path.realpath(s.get("cwd", ""))
        if s_cwd == norm_path or s_cwd.startswith(norm_path + os.sep):
            matching_sessions.append(s)

    if matching_sessions:
        # Corroboration: tmux is the only independent signal for whether a hook's
        # active state is still real. If tmux has no visibility at all (no panes
        # anywhere), nothing can be corroborated, so we trust the hook rather than
        # declare every agent dead just because tmux isn't running. If tmux does
        # have visibility, an active state is only corroborated when some pane in
        # this worktree is actually running an agent command.
        has_agent_pane = any(
            _pane_in_worktree(p["path"], norm_path) and p["command"] in AGENT_COMMANDS
            for p in panes
        )
        tmux_has_visibility = bool(panes)

        # A crashed session's hook file is never updated again, so when two
        # session files claim an active state for the same cwd, the most
        # recently-updated one is the one tmux is actually seeing; any other,
        # older active claim for that same cwd is an abandoned leftover, no
        # matter how "urgent" its raw state would otherwise rank.
        active_since = [s.get("since", "") for s in matching_sessions
                        if s.get("state") in ACTIVE_STATES]
        most_recent_active = max(active_since) if active_since else None

        # Compute the effective (post-staleness) state for every candidate
        # *before* ranking by priority, so a live session always wins on its own
        # merits instead of losing to a dead session's raw, pre-staleness state.
        effective: list[tuple[str, dict]] = []
        for s in matching_sessions:
            state = s.get("state", "unknown")
            if state in ACTIVE_STATES and tmux_has_visibility:
                if not has_agent_pane or s.get("since", "") != most_recent_active:
                    state = "stale"
            effective.append((state, s))

        # Sort by priority (ascending), then by since (descending, most recent
        # first). Stable sort: sort by since first (descending), then by
        # priority (ascending).
        effective.sort(key=lambda item: item[1].get("since", ""), reverse=True)
        effective.sort(key=lambda item: state_priority.get(item[0], 5))

        state, s = effective[0]
        pid = s.get("pid")
        return AgentState(state, "hook", s.get("since"), pid, window)

    for p in panes:
        if p["path"] == path and p["command"] in AGENT_COMMANDS:
            return AgentState("unknown", "liveness", None, p["pid"], p["window"])

    return AgentState("none", "none", None, None, window)
