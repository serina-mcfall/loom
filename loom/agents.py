"""What each agent is doing. Hooks say what; the process list says whether it exists."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .runner import Runner

TMUX_FORMAT = "#{pane_current_path}\t#{pane_current_command}\t#{pane_pid}\t#{window_name}"
ACTIVE_STATES = {"working", "waiting", "idle"}
AGENT_COMMANDS = {"claude", "node"}

# How long an uncorroborated claim survives before it is called stale.
#
# `working` gets 15 minutes. The hook rewrites `since` on every tool call, so a
# working agent's timestamp advances constantly.
#
# 15 min clears the one gap the harness DOES bound: a single Bash call is capped
# at 600s. It does NOT bound everything, and an earlier version of this comment
# wrongly claimed it did. An MCP tool call carries no such cap, and neither does a
# long unbroken generation with no tool call at all — so a live agent CAN read
# `stale` here. That is the acceptable direction (a false `stale` costs a glance)
# but it is a real false-positive source, and anyone tuning this number should
# know the bound is partial rather than total.
WORKING_STALE_SECONDS = 15 * 60

# `waiting` and `idle` get 12 hours, because they are legitimately parked — a
# `waiting` agent is blocked on a human BY DEFINITION and does not refresh its
# timestamp while it waits. But it cannot wait forever: a day-old `waiting` file
# would pin rank 1 permanently, and a strip that is never empty is a strip nobody
# reads. This bound is what keeps the alert meaningful.
PARKED_STALE_SECONDS = 12 * 60 * 60

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
    # Seconds since the winning session last refreshed, or None when that
    # cannot be determined (missing, unreadable, naive or future timestamp).
    # None means CANNOT TELL and must never be read as zero. Exposed because
    # `state` alone cannot distinguish a live blocked agent from a dead one,
    # and rank 1 needs to know the difference.
    age_seconds: float | None = None


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


def _age_seconds(since: str | None, now: datetime) -> float | None:
    """Seconds between `since` and `now`, or None if it cannot be determined.

    None is a real answer and callers must treat it as "cannot tell", never as
    zero and never as infinite. A missing or malformed timestamp is exactly the
    case where guessing produces the confident wrong answer this module exists
    to prevent.
    """
    if not since:
        return None
    try:
        stamp = datetime.fromisoformat(since)
    except (TypeError, ValueError):
        return None

    # A NAIVE STAMP IS UNANSWERABLE, NOT ASSUMABLE.
    #
    # An earlier version adopted `now`'s zone, which produced a zone-dependent
    # answer: the same record, the same real age, read `stale` at UTC+12 and
    # `working` at UTC-06. In any negative-offset zone a dead agent read alive
    # for up to |offset| hours — the forbidden direction — and neither the UTC
    # fixtures nor a check on a +12 machine could see it, because +12 pushed the
    # error the safe way.
    #
    # `reap()` already refuses to act on a naive `since` (collect.py). This now
    # matches it: one input, one meaning, across the whole snapshot.
    if stamp.tzinfo is None:
        return None
    if now.tzinfo is None:
        # Symmetrical: an unusable clock is as unanswerable as an unusable stamp.
        # Previously this raised TypeError out of collect() and killed the entire
        # snapshot, and no test watched which clock collect() passed.
        return None

    age = (now - stamp).total_seconds()
    if age < 0:
        # A timestamp in the future is evidence of a broken producer — a clock
        # correction, a record copied from a machine ahead — not evidence of
        # health. `age > limit` would silently never fire on a negative age and
        # report `working` indefinitely.
        return None
    return age


def agent_for(path: str, sessions: list[dict], panes: list[dict],
              now: datetime) -> AgentState:
    """Resolve one worktree's agent state.

    `now` is required rather than defaulted. A default would make staleness
    depend on an invisible clock, and the one thing this function must not do is
    decide an agent is dead for an unstated reason.
    """
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
        # STALENESS IS DECIDED BY TIMESTAMP FRESHNESS, NOT BY COUNTING PANES.
        #
        # It used to be counting, and that made Loom lie about live agents. The old
        # rule read: tmux has panes somewhere but none in this worktree, therefore
        # the agent here is gone. That inference does not hold — tmux running proves
        # nothing about where agents live. An agent in a plain terminal, a VS Code
        # terminal, or a pane whose cwd differs has zero panes "here" while being
        # entirely alive. On 2026-08-03 this reported the very session that was
        # reading the snapshot as `stale`.
        #
        # Counting cannot work in principle either: pane count cannot bound how many
        # agents are alive when agents need no pane at all. So the surplus rule
        # (`panes_here < active` -> stale the rest) was unsound for the same reason
        # and is gone with it.
        #
        # The signal that DOES work is already in the data. The hook rewrites
        # `since` on every event, so a live session's timestamp keeps advancing and
        # a dead one's freezes. A dead process cannot update a clock.
        #
        # Panes take NO part in staleness now, in either direction. A first attempt
        # let a pane in the worktree exempt sessions from ageing, but a pane cannot
        # be attributed to a particular session — the recorded pid is the hook's own
        # transient process — so one pane exempted every session there, and a dead
        # session beside a live one would keep reporting `working`. That is the
        # forbidden direction: a false `stale` says "look at this" and costs a
        # glance, a false `working` says "all is well" and is the lie this module
        # exists to prevent.
        stale_ids: set[int] = set()
        for s in matching_sessions:
            if s.get("state") not in ACTIVE_STATES:
                continue                    # stopped/unknown are already terminal
            age = _age_seconds(s.get("since"), now)
            if age is None:
                continue                    # cannot tell: never conclude death
            limit = (WORKING_STALE_SECONDS if s.get("state") == "working"
                     else PARKED_STALE_SECONDS)
            if age > limit:
                stale_ids.add(id(s))

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
        return AgentState(state, "hook", s.get("since"), pid, window,
                          _age_seconds(s.get("since"), now))

    for p in panes:
        if p["path"] == path and p["command"] in AGENT_COMMANDS:
            return AgentState("unknown", "liveness", None, p["pid"], p["window"])

    return AgentState("none", "none", None, None, window)
