import json
import tempfile
import unittest
from pathlib import Path

from loom.runner import ReplayRunner
from loom.agents import read_state_dir, tmux_panes, agent_for

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
        a = agent_for("/t/one", sessions, [])
        self.assertEqual((a.state, a.source), ("waiting", "hook"))

    def test_branch_panes_elsewhere_only_stales_every_active_session(self):
        # Branch: panes is non-empty but panes_here == 0 -> tmux has visibility,
        # none of it in this worktree, so the agent here is gone.
        sessions = [{"cwd": "/t/one", "state": "working", "pid": 42, "since": "T"}]
        panes = [{"path": "/t/other", "command": "claude", "pid": 7, "window": "wm"}]
        self.assertEqual(agent_for("/t/one", sessions, panes).state, "stale")

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
        a = agent_for("/t/one", sessions, panes)
        self.assertEqual(a.state, "waiting")

    def test_branch_panes_here_below_active_count_stales_the_oldest_surplus(self):
        # Branch: panes_here (1) < active (2) -> the surplus must be dead. Only
        # one pane exists, so only the freshest active session (the live
        # `working` one) is kept; the crashed, older `waiting` file is staled,
        # regardless of `waiting` normally outranking `working` on priority.
        sessions = [
            {"cwd": "/t/one", "state": "waiting", "pid": 999, "since": "2026-08-01T00:00:00"},
            {"cwd": "/t/one", "state": "working", "pid": 123, "since": "2026-08-03T09:00:00"},
        ]
        panes = [{"path": "/t/one", "command": "claude", "pid": 123, "window": "wm-one"}]
        a = agent_for("/t/one", sessions, panes)
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
        self.assertEqual(agent_for("/t/one", sessions, panes).state, "working")

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
            self.assertEqual(agent_for("/t/one", sessions, panes).state, "stopped")

    def test_stopped_is_inert_alongside_active_sessions_in_every_branch(self):
        # A `stopped` session sitting next to active ones must never be pulled
        # into the active count or the staleness surplus in any branch; the
        # winner must still resolve exactly as it would without it present.
        stopped = {"cwd": "/t/one", "state": "stopped", "pid": 9, "since": "2026-07-01T00:00:00"}

        # branch: no visibility at all
        sessions = [stopped, {"cwd": "/t/one", "state": "waiting", "pid": 1, "since": "T"}]
        self.assertEqual(agent_for("/t/one", sessions, []).state, "waiting")

        # branch: panes elsewhere only
        sessions = [stopped, {"cwd": "/t/one", "state": "working", "pid": 2, "since": "T"}]
        panes = [{"path": "/t/other", "command": "claude", "pid": 7, "window": "wm"}]
        self.assertEqual(agent_for("/t/one", sessions, panes).state, "stale")

        # branch: panes_here (1) >= active (1)
        sessions = [stopped, {"cwd": "/t/one", "state": "working", "pid": 3, "since": "T"}]
        panes = [{"path": "/t/one", "command": "claude", "pid": 3, "window": "wm"}]
        self.assertEqual(agent_for("/t/one", sessions, panes).state, "working")

        # branch: panes_here (1) < active (2)
        sessions = [
            stopped,
            {"cwd": "/t/one", "state": "waiting", "pid": 4, "since": "2026-08-01T00:00:00"},
            {"cwd": "/t/one", "state": "working", "pid": 5, "since": "2026-08-03T09:00:00"},
        ]
        panes = [{"path": "/t/one", "command": "claude", "pid": 5, "window": "wm"}]
        self.assertEqual(agent_for("/t/one", sessions, panes).state, "working")

    def test_a_live_claude_with_no_hook_is_unknown_not_working(self):
        panes = [{"path": "/t/one", "command": "claude", "pid": 7, "window": "wm-one"}]
        a = agent_for("/t/one", [], panes)
        self.assertEqual((a.state, a.source), ("unknown", "liveness"))

    def test_a_shell_alone_is_not_an_agent(self):
        panes = [{"path": "/t/one", "command": "zsh", "pid": 7, "window": "wm-one"}]
        self.assertEqual(agent_for("/t/one", [], panes).state, "none")

    def test_nothing_anywhere_is_none(self):
        self.assertEqual(agent_for("/t/one", [], []).state, "none")

    def test_session_in_subdirectory_is_matched(self):
        sessions = [{"cwd": "/t/one/sub", "state": "working", "pid": 42, "since": "T"}]
        a = agent_for("/t/one", sessions, [])
        self.assertEqual((a.state, a.source), ("working", "hook"))

    def test_session_cwd_with_trailing_slash_is_matched(self):
        sessions = [{"cwd": "/t/one/", "state": "working", "pid": 42, "since": "T"}]
        a = agent_for("/t/one", sessions, [])
        self.assertEqual((a.state, a.source), ("working", "hook"))

    def test_similar_path_does_not_match(self):
        sessions = [{"cwd": "/t/one-other", "state": "working", "pid": 42, "since": "T"}]
        self.assertEqual(agent_for("/t/one", sessions, []).state, "none")

    def test_waiting_beats_idle_by_priority(self):
        sessions = [
            {"cwd": "/t/one", "state": "idle", "pid": 42, "since": "2026-08-03T10:20:00"},
            {"cwd": "/t/one", "state": "waiting", "pid": 43, "since": "2026-08-03T10:19:00"},
        ]
        a = agent_for("/t/one", sessions, [])
        self.assertEqual(a.state, "waiting")

    def test_newer_working_wins_over_older_working(self):
        sessions = [
            {"cwd": "/t/one", "state": "working", "pid": 42, "since": "2026-08-03T10:19:00"},
            {"cwd": "/t/one", "state": "working", "pid": 43, "since": "2026-08-03T10:20:00"},
        ]
        a = agent_for("/t/one", sessions, [])
        self.assertEqual(a.pid, 43)


if __name__ == "__main__":
    unittest.main()
