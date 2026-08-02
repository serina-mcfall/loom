# tests/test_collect.py
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from loom.gitsrc import Worktree
from loom.ghsrc import PullRequest
from loom.collect import find_flags, reap, SCHEMA_VERSION

NOW = datetime(2026, 8, 3, 8, 0, 0, tzinfo=timezone.utc)


def pr(number, branch):
    return PullRequest(number, "t", branch, False, None, "none", "2026-08-03T00:00:00Z")


class TestFindFlags(unittest.TestCase):
    def test_pr_whose_branch_has_no_worktree_is_an_orphan(self):
        trees = [Worktree("/t/a", "a", "feature-a", "h")]
        flags = find_flags(trees, [pr(56, "fix/other")], "/t", lambda d: ["a"])
        self.assertEqual([f["kind"] for f in flags], ["orphan_pr"])
        self.assertIn("56", flags[0]["subject"])

    def test_pr_with_a_worktree_is_not_flagged(self):
        trees = [Worktree("/t/a", "a", "feature-a", "h")]
        self.assertEqual(find_flags(trees, [pr(1, "feature-a")], "/t", lambda d: ["a"]), [])

    def test_directory_that_is_not_a_worktree_is_stale(self):
        trees = [Worktree("/t/a", "a", "feature-a", "h")]
        flags = find_flags(trees, [], "/t", lambda d: ["a", "leftover"])
        self.assertEqual([f["kind"] for f in flags], ["stale_dir"])
        self.assertIn("leftover", flags[0]["subject"])

    def test_a_tidy_fleet_produces_no_flags(self):
        # The negative control: this must be able to return nothing.
        trees = [Worktree("/t/a", "a", "feature-a", "h")]
        self.assertEqual(find_flags(trees, [pr(1, "feature-a")], "/t", lambda d: ["a"]), [])

    def test_hidden_directories_are_ignored(self):
        trees = [Worktree("/t/a", "a", "feature-a", "h")]
        self.assertEqual(find_flags(trees, [], "/t", lambda d: ["a", ".workmux_trash_x"]), [])


class TestSchema(unittest.TestCase):
    def test_version_is_pinned(self):
        self.assertEqual(SCHEMA_VERSION, 1)


class TestReap(unittest.TestCase):
    """The spec requires stopped sessions to be cleared after 24 hours."""

    def _dir_with(self, state, since):
        d = tempfile.mkdtemp()
        Path(d, "s1.json").write_text(json.dumps(
            {"session_id": "s1", "cwd": "/t/a", "state": state, "since": since, "pid": 1}))
        return d

    def test_removes_a_session_stopped_longer_than_the_window(self):
        d = self._dir_with("stopped", "2026-08-01T00:00:00+00:00")
        self.assertEqual(reap(d, 24, NOW), 1)
        self.assertEqual(list(Path(d).glob("*.json")), [])

    def test_keeps_a_session_stopped_recently(self):
        d = self._dir_with("stopped", "2026-08-03T07:00:00+00:00")
        self.assertEqual(reap(d, 24, NOW), 0)

    def test_never_removes_an_active_session_however_old(self):
        # Negative control: age alone must not be enough to delete state.
        d = self._dir_with("working", "2026-07-01T00:00:00+00:00")
        self.assertEqual(reap(d, 24, NOW), 0)

    def test_a_missing_directory_is_not_an_error(self):
        self.assertEqual(reap("/does/not/exist", 24, NOW), 0)


if __name__ == "__main__":
    unittest.main()
