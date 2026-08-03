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
    def test_hook_state_wins_when_tmux_has_no_visibility_at_all(self):
        # panes == [] means tmux isn't running (or isn't watched), so there is
        # nothing to corroborate against. The hook must be trusted, not downgraded.
        sessions = [{"cwd": "/t/one", "state": "waiting", "pid": 42, "since": "T"}]
        a = agent_for("/t/one", sessions, [])
        self.assertEqual((a.state, a.source), ("waiting", "hook"))

    def test_active_state_with_no_matching_agent_pane_becomes_stale(self):
        sessions = [{"cwd": "/t/one", "state": "working", "pid": 42, "since": "T"}]
        panes = [{"path": "/t/other", "command": "zsh", "pid": 7, "window": "wm"}]
        self.assertEqual(agent_for("/t/one", sessions, panes).state, "stale")

    def test_active_state_with_a_matching_agent_pane_is_corroborated(self):
        sessions = [{"cwd": "/t/one", "state": "working", "pid": 42, "since": "T"}]
        panes = [{"path": "/t/one", "command": "claude", "pid": 7, "window": "wm"}]
        self.assertEqual(agent_for("/t/one", sessions, panes).state, "working")

    def test_stopped_never_becomes_stale_regardless_of_panes(self):
        cases = [
            [],
            [{"path": "/t/other", "command": "zsh", "pid": 7, "window": "wm"}],
            [{"path": "/t/one", "command": "claude", "pid": 7, "window": "wm"}],
        ]
        for panes in cases:
            sessions = [{"cwd": "/t/one", "state": "stopped", "pid": 1, "since": "T"}]
            self.assertEqual(agent_for("/t/one", sessions, panes).state, "stopped")

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

    def test_crashed_waiting_does_not_outrank_live_working(self):
        # The Blocker's regression guard. A session crashed mid-`waiting` (dead pid,
        # never reaped) shares a worktree with a genuinely live `working` session.
        # `waiting` outranks `working` by raw priority, but tmux corroborates the
        # `working` session's pane, so the crashed one must be downgraded to `stale`
        # *before* sorting — the live session should win outright, not get demoted
        # to `stale` after already being selected.
        sessions = [
            {"cwd": "/t/one", "state": "waiting", "pid": 999, "since": "2026-08-01T00:00:00"},
            {"cwd": "/t/one", "state": "working", "pid": 123, "since": "2026-08-03T09:00:00"},
        ]
        panes = [{"path": "/t/one", "command": "claude", "pid": 123, "window": "wm-one"}]
        a = agent_for("/t/one", sessions, panes)
        self.assertEqual(a.state, "working")
        self.assertEqual(a.pid, 123)


if __name__ == "__main__":
    unittest.main()
