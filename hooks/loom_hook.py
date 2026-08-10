"""Claude Code calls this on each event. It writes state, and nothing else.

Deliberately records no prompt, no output, no tool input and no transcript path.
A local web server must never become a place a transcript can leak from.

The recorded pid is a DEBUGGING AID, not a liveness signal. A command hook runs
under `sh -c`, so os.getppid() is that transient shell wrapper's pid, which exits
within milliseconds — verified by execution 2026-08-03. Staleness is decided by
corroboration against the process list instead; see loom/agents.py.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

# Events whose state is the same no matter what the payload contains.
#
# "Notification" is listed here too, mapped to None, purely so this dict stays
# the single source of truth for "which events does Loom register a hook for"
# (hookinstall.merge() iterates these keys). Its actual state is NEVER looked
# up through this dict — see _notification_state below.
STATE_FOR_EVENT: dict[str, str | None] = {
    "SessionStart": "idle",
    "UserPromptSubmit": "working",
    "PreToolUse": "working",
    "Notification": None,
    "Stop": "idle",
    "SessionEnd": "stopped",
}

# Notification fires for several unrelated reasons, not only permission
# prompts. Mapping every Notification to "waiting" would report a *finished*
# background agent as blocked on a human — the dashboard's highest-priority
# row, cried wolf on the one alert that has to stay trustworthy.
#
# So the mapping is explicit and narrow. Confirmed from the Claude Code hooks
# documentation, notification_type values:
#   permission_prompt   -> a human must approve something right now: waiting
#   agent_needs_input   -> a background agent needs input right now: waiting
#   idle_prompt         -> Claude finished and is awaiting a new prompt: idle
#   auth_success        -> informational only: write nothing
#   agent_completed      -> a background agent finished, not blocked: write nothing
#
# Anything else — a missing notification_type, or a type Loom has never seen
# (e.g. a future "some_future_type") — also writes nothing. When unsure,
# staying silent is the safe direction; claiming "waiting" is not.
BLOCKING_NOTIFICATIONS = {"permission_prompt", "agent_needs_input"}
IDLE_NOTIFICATIONS = {"idle_prompt"}

DEFAULT_STATE_DIR = os.path.expanduser("~/.loom/state")


def _notification_state(payload: dict) -> str | None:
    """Map a Notification event's notification_type to a Loom state, or None
    to mean "write nothing" — the deliberate default for anything unrecognised.
    """
    notification_type = payload.get("notification_type")
    if notification_type in BLOCKING_NOTIFICATIONS:
        return "waiting"
    if notification_type in IDLE_NOTIFICATIONS:
        return "idle"
    return None


def handle(event: str, payload: dict, state_dir: str, now: str, pid: int) -> dict | None:
    """Turn one Claude Code hook event into a state-file write, or nothing.

    Writes only six fields: session_id, cwd, state, tool, since, pid. Never the
    prompt, tool input, transcript path, or anything else the payload carries —
    those exist upstream, and this hook is not the place they get copied to.
    """
    session_id = payload.get("session_id")
    if not session_id:
        return None

    state = _notification_state(payload) if event == "Notification" else STATE_FOR_EVENT.get(event)
    if state is None:
        return None

    record = {
        "session_id": session_id,
        "cwd": payload.get("cwd", ""),
        "state": state,
        "tool": payload.get("tool_name") if event == "PreToolUse" else None,
        "since": now,
        "pid": pid,
    }
    Path(state_dir).mkdir(parents=True, exist_ok=True)
    # Per-process temp name: a single session can fire PreToolUse concurrently
    # when a turn issues parallel tool calls, and two invocations racing on the
    # same ".<session_id>.tmp" path would clobber or FileNotFoundError each
    # other's replace(). Each process gets its own temp file; the final
    # replace() onto "<session_id>.json" stays atomic, and whichever write
    # lands last on the real file wins -- which is correct, since the newest
    # state is the one we want.
    tmp = Path(state_dir, f".{session_id}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(record))
    tmp.replace(Path(state_dir, f"{session_id}.json"))
    return record


def main() -> int:
    event = sys.argv[1] if len(sys.argv) > 1 else ""
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        payload = {}
    now = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
    try:
        handle(event, payload, DEFAULT_STATE_DIR, now, os.getppid())
    except OSError as exc:
        # Per the Claude Code hooks docs: exit 2 is a blocking error, ANY OTHER
        # non-zero exit is non-blocking -- the triggering tool call proceeds --
        # and the first line of stderr is shown in the transcript. Exit 0 is the
        # one code that is both non-blocking AND silent: its stdout is parsed as
        # JSON for a decision, and its stderr goes nowhere.
        #
        # THIS RETURNED 0, AND THE COMMENT CLAIMED THAT WAS VISIBLE. It was not.
        # Measured 2026-08-06 with two identical UserPromptSubmit hooks in one
        # run, differing only in exit code:
        #
        #   echo CANARY >&2 ; exit 0   -> 0 occurrences in the transcript
        #   echo CANARY >&2 ; exit 1   -> 1 occurrence
        #
        # and guarded against the vacuous reading -- that the exit-0 hook simply
        # never fired -- by having it also write a witness file. The witness was
        # written; its stderr still never appeared. So the hook ran and its
        # complaint vanished.
        #
        # The intent was "visible but non-blocking", which is exactly what a
        # non-zero, non-2 exit gives. Exit 0 gave silent-and-non-blocking: when
        # the state write failed, the board quietly stopped updating and nothing
        # said so. Returning 1 keeps every property the original wanted and adds
        # the one it thought it already had.
        #
        # SCOPE, so this is not read as a general guarantee: it covers an OSError
        # raised by the write, and nothing else. A malformed payload still no-ops
        # in silence -- json.load fails above, payload becomes {}, handle()
        # returns None on the missing session_id, and this returns 0. Left that
        # way deliberately: Claude Code sends valid JSON, so a decode failure
        # means something stranger than a full disk and wants its own diagnosis,
        # not this message. The board can still go stale for that reason.
        print(f"loom hook: could not write state: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
