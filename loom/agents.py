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
        # Corroboration is counting, not ranking. Recency tells us *which*
        # session is still alive; it must never be used to decide *which state
        # matters most* — that is priority's job, below, and priority alone.
        panes_here = sum(
            1 for p in panes
            if _pane_in_worktree(p["path"], norm_path) and p["command"] in AGENT_COMMANDS
        )
        active_sessions = [s for s in matching_sessions if s.get("state") in ACTIVE_STATES]
        active = len(active_sessions)

        stale_ids: set[int] = set()
        if not panes:
            # No tmux visibility at all: nothing can be corroborated either way,
            # so trust every hook state as-is rather than declare everything
            # dead just because tmux isn't running.
            pass
        elif panes_here == 0:
            # tmux has visibility, but none of it is in this worktree: the
            # agent is gone. Every active claim here is stale.
            stale_ids = {id(s) for s in active_sessions}
        elif panes_here < active:
            # Fewer corroborating panes than active claims: the surplus must be
            # dead. Keep the `panes_here` freshest by `since` as live — a live
            # session keeps updating its timestamp, a crashed one doesn't — and
            # stale the rest, regardless of their raw priority.
            ranked = sorted(active_sessions, key=lambda s: s.get("since", ""), reverse=True)
            stale_ids = {id(s) for s in ranked[panes_here:]}
        # else panes_here >= active: every active claim could be live; stale nothing.

        # Compute the effective (post-staleness) state for every candidate
        # *before* ranking by priority, so a live session always wins on its own
        # merits instead of losing to a dead session's raw, pre-staleness state.
        effective: list[tuple[str, dict]] = []
        for s in matching_sessions:
            state = s.get("state", "unknown")
            if id(s) in stale_ids:
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
