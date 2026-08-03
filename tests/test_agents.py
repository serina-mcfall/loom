import json
import tempfile
import unittest
from pathlib import Path

from loom.runner import ReplayRunner
from datetime import datetime, timedelta, timezone

from loom.agents import (read_state_dir, tmux_panes, agent_for,
                         WORKING_STALE_SECONDS, PARKED_STALE_SECONDS)

# A fixed clock. `agent_for` requires `now` precisely so no test can depend on
# an invisible one, and so every timestamp below states its age on purpose.
NOW = datetime(2026, 8, 3, 12, 0, 0, tzinfo=timezone.utc)


def ago(seconds: float) -> str:
    """An ISO timestamp exactly `seconds` before NOW."""
    return (NOW - timedelta(seconds=seconds)).isoformat()


TMUX_FMT = ("tmux list-panes -a -F "
            "#{pane_current_path}\t#{pane_current_command}\t#{pane_pid}\t#{window_name}")


class TestReadStateDir(unittest.TestCase):
    def test_missing_directory_is_empty_not_an_error(self):
        self.assertEqual(read_state_dir("/does/not/exist"), [])

    def test_reads_each_session_file(self):
        with tempfile.TemporaryDirectory() as d:
            Path(d, "abc.json").write_text(json.dumps(
                {"session_id": "abc", "cwd": "/t/one", "state": "working", "pid": 42}))
            self.assertEqual(read_state_dir(d)[0]["session_id"], "abc")

    def test_corrupt_file_is_skipped_not_fatal(self):
        with tempfile.TemporaryDirectory() as d:
            Path(d, "bad.json").write_text("{not json")
            Path(d, "good.json").write_text(json.dumps(
                {"session_id": "g", "cwd": "/t/one", "state": "idle", "pid": 1}))
            self.assertEqual([s["session_id"] for s in read_state_dir(d)], ["g"])


class TestTmuxPanes(unittest.TestCase):
    def test_parses_panes(self):
        runner = ReplayRunner({TMUX_FMT: {
            "returncode": 0,
            "stdout": "/t/one\tclaude\t2129918\twm-one\n/t/one\tzsh\t2129940\twm-one\n",
            "stderr": "",
        }})
        panes = tmux_panes(runner)
        self.assertEqual(panes[0], {"path": "/t/one", "command": "claude",
                                    "pid": 2129918, "window": "wm-one"})

    def test_no_tmux_server_is_empty_not_an_error(self):
        runner = ReplayRunner({TMUX_FMT: {
            "returncode": 1, "stdout": "", "stderr": "no server running"}})
        self.assertEqual(tmux_panes(runner), [])


class TestAgentFor(unittest.TestCase):
    # --- staleness: counting, not ranking. Each test names its branch. ---

    def test_branch_panes_empty_entirely_preserves_every_hook_state(self):
        # Branch: panes == [] -> no tmux visibility at all, nothing to
        # corroborate either way, so the hook is trusted as-is.
        sessions = [{"cwd": "/t/one", "state": "waiting", "pid": 42, "since": "T"}]
        a = agent_for("/t/one", sessions, [], NOW)
        self.assertEqual((a.state, a.source), ("waiting", "hook"))

    def test_a_fresh_session_with_no_pane_in_this_worktree_is_NOT_stale(self):
        # THE REGRESSION GUARD FOR ISSUE #9. This test previously asserted the
        # opposite, and the opposite was a lie.
        #
        # The old rule: tmux has panes somewhere, none here, therefore the agent
        # here is gone. That inference does not hold. An agent in a plain
        # terminal, a VS Code terminal, or a pane whose cwd differs has no pane
        # "here" while being entirely alive — and on 2026-08-03 Loom reported the
        # very session reading the snapshot as `stale` for exactly this reason.
        sessions = [{"cwd": "/t/one", "state": "working", "pid": 42, "since": ago(5)}]
        panes = [{"path": "/t/other", "command": "claude", "pid": 7, "window": "wm"}]
        self.assertEqual(agent_for("/t/one", sessions, panes, NOW).state, "working")

    def test_the_absence_of_any_pane_at_all_does_not_stale_a_fresh_session(self):
        # Same guarantee with no tmux running whatsoever. Absence of tmux is not
        # evidence about agents.
        sessions = [{"cwd": "/t/one", "state": "working", "pid": 42, "since": ago(5)}]
        self.assertEqual(agent_for("/t/one", sessions, [], NOW).state, "working")

    def test_a_working_session_past_the_limit_is_stale(self):
        # The positive control for the same mechanism: without this, the test
        # above could pass simply because nothing is ever staled.
        sessions = [{"cwd": "/t/one", "state": "working", "pid": 42,
                     "since": ago(WORKING_STALE_SECONDS + 60)}]
        self.assertEqual(agent_for("/t/one", sessions, [], NOW).state, "stale")

    def test_a_working_session_just_inside_the_limit_survives(self):
        # The boundary, from the safe side.
        sessions = [{"cwd": "/t/one", "state": "working", "pid": 42,
                     "since": ago(WORKING_STALE_SECONDS - 60)}]
        self.assertEqual(agent_for("/t/one", sessions, [], NOW).state, "working")

    def test_a_pane_here_does_NOT_exempt_an_aged_session(self):
        # A pane cannot be attributed to a session (the recorded pid is the hook's
        # own transient process), so letting one pane exempt every session in the
        # worktree would let a dead session report `working` beside a live one.
        # Age decides regardless of panes.
        sessions = [{"cwd": "/t/one", "state": "working", "pid": 42,
                     "since": ago(WORKING_STALE_SECONDS + 60)}]
        panes = [{"path": "/t/one", "command": "claude", "pid": 7, "window": "wm"}]
        self.assertEqual(agent_for("/t/one", sessions, panes, NOW).state, "stale")

    def test_waiting_is_not_staled_by_a_gap_that_would_kill_working(self):
        # `waiting` means blocked on a human BY DEFINITION, so it does not refresh
        # its timestamp while it waits. Ageing it on the `working` limit would make
        # rank 1 vanish minutes after the prompt appeared — the opposite of useful.
        sessions = [{"cwd": "/t/one", "state": "waiting", "pid": 42,
                     "since": ago(WORKING_STALE_SECONDS * 4)}]
        self.assertEqual(agent_for("/t/one", sessions, [], NOW).state, "waiting")

    def test_waiting_past_the_parked_limit_is_stale(self):
        # But it cannot wait forever. A day-old `waiting` file would pin rank 1
        # permanently, and a strip that is never empty is a strip nobody reads.
        sessions = [{"cwd": "/t/one", "state": "waiting", "pid": 42,
                     "since": ago(PARKED_STALE_SECONDS + 60)}]
        self.assertEqual(agent_for("/t/one", sessions, [], NOW).state, "stale")

    def test_an_unreadable_timestamp_is_never_treated_as_old(self):
        # Age unknown must not become age infinite. "I cannot tell" degrades to
        # keeping the reported state, not to declaring death.
        for bad in ("T", "", None, "not-a-date", "2026-13-45T99:99:99"):
            sessions = [{"cwd": "/t/one", "state": "working", "pid": 42, "since": bad}]
            self.assertEqual(agent_for("/t/one", sessions, [], NOW).state, "working",
                             f"since={bad!r} should leave the state alone")

    def test_a_missing_since_key_entirely_is_not_stale(self):
        sessions = [{"cwd": "/t/one", "state": "working", "pid": 42}]
        self.assertEqual(agent_for("/t/one", sessions, [], NOW).state, "working")

    def test_a_naive_timestamp_is_aged_rather_than_crashing(self):
        # The hook writes tz-aware stamps, but a hand-edited or older file may be
        # naive. Comparing naive to aware raises TypeError, which previously took
        # out the whole of collect().
        naive_old = (NOW - timedelta(seconds=PARKED_STALE_SECONDS + 60)).replace(tzinfo=None)
        sessions = [{"cwd": "/t/one", "state": "waiting", "pid": 42,
                     "since": naive_old.isoformat()}]
        self.assertEqual(agent_for("/t/one", sessions, [], NOW).state, "stale")

    def test_branch_panes_here_equals_active_count_nothing_staled_waiting_wins(self):
        # Branch: panes_here (2) >= active (2) -> nothing is staled. This is the
        # regression guard: two genuinely live sessions (one blocked on a
        # prompt, one busy) must both survive so priority alone decides the
        # winner. A "most recently updated wins" rule would wrongly hide the
        # blocked `waiting` session behind the busier `working` one — this must
        # not come back silently.
        sessions = [
            {"cwd": "/t/one", "state": "waiting", "pid": 1, "since": "2026-08-03T09:00:00"},
            {"cwd": "/t/one", "state": "working", "pid": 2, "since": "2026-08-03T09:05:00"},
        ]
        panes = [
            {"path": "/t/one", "command": "claude", "pid": 1, "window": "wm-a"},
            {"path": "/t/one", "command": "claude", "pid": 2, "window": "wm-b"},
        ]
        a = agent_for("/t/one", sessions, panes, NOW)
        self.assertEqual(a.state, "waiting")

    def test_branch_panes_here_below_active_count_stales_the_oldest_surplus(self):
        # Branch: panes_here (1) < active (2) -> the surplus must be dead. Only
        # one pane exists, so only the freshest active session (the live
        # `working` one) is kept; the crashed, older `waiting` file is staled,
        # regardless of `waiting` normally outranking `working` on priority.
        sessions = [
            # abandoned days ago -> past the parked limit -> stale
            {"cwd": "/t/one", "state": "waiting", "pid": 999,
             "since": ago(PARKED_STALE_SECONDS * 5)},
            # refreshed seconds ago -> demonstrably alive
            {"cwd": "/t/one", "state": "working", "pid": 123, "since": ago(3)},
        ]
        panes = [{"path": "/t/one", "command": "claude", "pid": 123, "window": "wm-one"}]
        a = agent_for("/t/one", sessions, panes, NOW)
        self.assertEqual(a.state, "working")
        self.assertEqual(a.pid, 123)

    def test_branch_panes_here_above_active_count_preserves_the_session(self):
        # Branch: panes_here (2) > active (1) -> nothing to stale. More visible
        # agent panes than active sessions is not evidence against the session.
        sessions = [{"cwd": "/t/one", "state": "working", "pid": 42, "since": "T"}]
        panes = [
            {"path": "/t/one", "command": "claude", "pid": 7, "window": "wm-a"},
            {"path": "/t/one", "command": "claude", "pid": 8, "window": "wm-b"},
        ]
        self.assertEqual(agent_for("/t/one", sessions, panes, NOW).state, "working")

    def test_stopped_never_becomes_stale_regardless_of_panes(self):
        # `stopped` is never counted as active and never staled, in the three
        # branches where a lone `stopped` session is even a coherent scenario
        # (active == 0, so "panes_here < active" cannot apply to it alone).
        cases = [
            [],  # branch: no visibility at all
            [{"path": "/t/other", "command": "claude", "pid": 7, "window": "wm"}],  # elsewhere only
            [{"path": "/t/one", "command": "claude", "pid": 7, "window": "wm"}],  # panes_here >= active (0)
        ]
        for panes in cases:
            sessions = [{"cwd": "/t/one", "state": "stopped", "pid": 1, "since": "T"}]
            self.assertEqual(agent_for("/t/one", sessions, panes, NOW).state, "stopped")

    def test_stopped_is_inert_alongside_active_sessions(self):
        # A `stopped` session next to active ones must never change the outcome:
        # it is not active, so it is never aged, and it must not win on priority.
        # `stopped` is the LOWEST priority, so a bug here would surface as the
        # worktree reporting `stopped` while an agent is plainly running in it.
        #
        # Its own timestamp is ancient on purpose — ageing must skip it entirely
        # rather than "stale" something already terminal.
        stopped = {"cwd": "/t/one", "state": "stopped", "pid": 9,
                   "since": ago(PARKED_STALE_SECONDS * 30)}

        # a live waiting session beside it
        sessions = [stopped, {"cwd": "/t/one", "state": "waiting", "pid": 1, "since": ago(30)}]
        self.assertEqual(agent_for("/t/one", sessions, [], NOW).state, "waiting")

        # a live working session, with panes visible elsewhere
        sessions = [stopped, {"cwd": "/t/one", "state": "working", "pid": 2, "since": ago(4)}]
        panes = [{"path": "/t/other", "command": "claude", "pid": 7, "window": "wm"}]
        self.assertEqual(agent_for("/t/one", sessions, panes, NOW).state, "working")

        # a live working session, with a pane here
        sessions = [stopped, {"cwd": "/t/one", "state": "working", "pid": 3, "since": ago(4)}]
        panes = [{"path": "/t/one", "command": "claude", "pid": 3, "window": "wm"}]
        self.assertEqual(agent_for("/t/one", sessions, panes, NOW).state, "working")

        # an abandoned waiting file beside a live working one: the dead one ages
        # out, the live one wins, and `stopped` still does not surface
        sessions = [
            stopped,
            {"cwd": "/t/one", "state": "waiting", "pid": 4, "since": ago(PARKED_STALE_SECONDS * 2)},
            {"cwd": "/t/one", "state": "working", "pid": 5, "since": ago(2)},
        ]
        panes = [{"path": "/t/one", "command": "claude", "pid": 5, "window": "wm"}]
        self.assertEqual(agent_for("/t/one", sessions, panes, NOW).state, "working")

        # and when EVERY active claim has aged out, the answer is `stale` — not
        # `stopped`, which would wrongly imply a clean shutdown
        sessions = [
            stopped,
            {"cwd": "/t/one", "state": "working", "pid": 6,
             "since": ago(WORKING_STALE_SECONDS + 60)},
        ]
        self.assertEqual(agent_for("/t/one", sessions, [], NOW).state, "stale")

    def test_a_live_claude_with_no_hook_is_unknown_not_working(self):
        panes = [{"path": "/t/one", "command": "claude", "pid": 7, "window": "wm-one"}]
        a = agent_for("/t/one", [], panes, NOW)
        self.assertEqual((a.state, a.source), ("unknown", "liveness"))

    def test_a_shell_alone_is_not_an_agent(self):
        panes = [{"path": "/t/one", "command": "zsh", "pid": 7, "window": "wm-one"}]
        self.assertEqual(agent_for("/t/one", [], panes, NOW).state, "none")

    def test_nothing_anywhere_is_none(self):
        self.assertEqual(agent_for("/t/one", [], [], NOW).state, "none")

    def test_session_in_subdirectory_is_matched(self):
        sessions = [{"cwd": "/t/one/sub", "state": "working", "pid": 42, "since": "T"}]
        a = agent_for("/t/one", sessions, [], NOW)
        self.assertEqual((a.state, a.source), ("working", "hook"))

    def test_session_cwd_with_trailing_slash_is_matched(self):
        sessions = [{"cwd": "/t/one/", "state": "working", "pid": 42, "since": "T"}]
        a = agent_for("/t/one", sessions, [], NOW)
        self.assertEqual((a.state, a.source), ("working", "hook"))

    def test_similar_path_does_not_match(self):
        sessions = [{"cwd": "/t/one-other", "state": "working", "pid": 42, "since": "T"}]
        self.assertEqual(agent_for("/t/one", sessions, [], NOW).state, "none")

    def test_waiting_beats_idle_by_priority(self):
        sessions = [
            {"cwd": "/t/one", "state": "idle", "pid": 42, "since": "2026-08-03T10:20:00"},
            {"cwd": "/t/one", "state": "waiting", "pid": 43, "since": "2026-08-03T10:19:00"},
        ]
        a = agent_for("/t/one", sessions, [], NOW)
        self.assertEqual(a.state, "waiting")

    def test_newer_working_wins_over_older_working(self):
        sessions = [
            {"cwd": "/t/one", "state": "working", "pid": 42, "since": "2026-08-03T10:19:00"},
            {"cwd": "/t/one", "state": "working", "pid": 43, "since": "2026-08-03T10:20:00"},
        ]
        a = agent_for("/t/one", sessions, [], NOW)
        self.assertEqual(a.pid, 43)


if __name__ == "__main__":
    unittest.main()
