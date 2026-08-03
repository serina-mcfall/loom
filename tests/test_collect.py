# tests/test_collect.py
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from loom.gitsrc import Worktree
from loom.ghsrc import PullRequest
from loom.runner import ReplayRunner
from loom.collect import find_flags, reap, collect, SCHEMA_VERSION

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
        flags = find_flags(trees, [], "/t", lambda d: ["a", "leftover"], lambda p: True)
        self.assertEqual([f["kind"] for f in flags], ["stale_dir"])
        self.assertIn("leftover", flags[0]["subject"])

    def test_a_tidy_fleet_produces_no_flags(self):
        # The negative control: this must be able to return nothing.
        trees = [Worktree("/t/a", "a", "feature-a", "h")]
        self.assertEqual(find_flags(trees, [pr(1, "feature-a")], "/t", lambda d: ["a"]), [])

    def test_hidden_directories_are_ignored(self):
        trees = [Worktree("/t/a", "a", "feature-a", "h")]
        self.assertEqual(find_flags(trees, [], "/t", lambda d: ["a", ".workmux_trash_x"]), [])

    def test_a_plain_file_is_not_flagged(self):
        trees = [Worktree("/t/a", "a", "feature-a", "h")]

        def listdir(d):
            return ["a", "notes.txt"] if d == "/t" else []

        def isdir(p):
            return p == "/t/a"  # notes.txt is a file, not a directory

        self.assertEqual(find_flags(trees, [], "/t", listdir, isdir), [])

    def test_a_directory_containing_dot_git_is_someone_elses_checkout_not_stale(self):
        trees = [Worktree("/t/a", "a", "feature-a", "h")]

        def listdir(d):
            if d == "/t":
                return ["a", "other-repo"]
            if d == "/t/other-repo":
                return [".git", "README.md"]
            return []

        self.assertEqual(find_flags(trees, [], "/t", listdir, lambda p: True), [])

    def test_a_directory_with_no_dot_git_is_still_flagged(self):
        # Positive control: the isdir/.git guard must not disable detection entirely.
        trees = [Worktree("/t/a", "a", "feature-a", "h")]

        def listdir(d):
            if d == "/t":
                return ["a", "leftover"]
            if d == "/t/leftover":
                return ["README.md"]
            return []

        flags = find_flags(trees, [], "/t", listdir, lambda p: True)
        self.assertEqual([f["kind"] for f in flags], ["stale_dir"])
        self.assertIn("leftover", flags[0]["subject"])


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

    def test_a_timezone_naive_since_is_skipped_not_a_crash(self):
        # A malformed state file must never take down the dashboard.
        d = self._dir_with("stopped", "2026-08-01T00:00:00")  # no offset
        self.assertEqual(reap(d, 24, NOW), 0)
        self.assertEqual(len(list(Path(d).glob("*.json"))), 1)


class TestCollectSources(unittest.TestCase):
    """Full-snapshot coverage for the two 'confident green' regressions this project exists to catch."""

    def _recordings(self, pr_result, issue_result):
        return {
            "git symbolic-ref --short refs/remotes/origin/HEAD":
                {"returncode": 0, "stdout": "origin/main\n", "stderr": ""},
            "git worktree list --porcelain": {
                "returncode": 0,
                "stdout": "worktree /repo\nHEAD abc123\nbranch refs/heads/main\n\n",
                "stderr": "",
            },
            "tmux list-panes -a -F #{pane_current_path}\t#{pane_current_command}\t"
            "#{pane_pid}\t#{window_name}":
                {"returncode": 1, "stdout": "", "stderr": "no server running"},
            "git rev-list --left-right --count main...HEAD":
                {"returncode": 0, "stdout": "0\t0\n", "stderr": ""},
            "git status --porcelain=v1": {"returncode": 0, "stdout": "", "stderr": ""},
            "git remote get-url origin":
                {"returncode": 0, "stdout": "git@github.com:you/example.git\n", "stderr": ""},
            "gh pr list -R you/example --state open --limit 50 --json "
            "number,title,headRefName,isDraft,reviewDecision,statusCheckRollup,updatedAt": pr_result,
            "gh issue list -R you/example --state open --limit 50 --json "
            "number,title,labels,assignees": issue_result,
            "git log -1 --format=%h%x1f%aI%x1f%s": {
                "returncode": 0,
                "stdout": "abc1234\x1f2026-08-03T07:00:00+12:00\x1fSome commit\n",
                "stderr": "",
            },
            "git merge-base main HEAD": {"returncode": 0, "stdout": "base1\n", "stderr": ""},
            "git diff --name-only -z base1 HEAD": {"returncode": 0, "stdout": "", "stderr": ""},
            "git diff --name-only -z HEAD": {"returncode": 0, "stdout": "", "stderr": ""},
            "git ls-files --others --exclude-standard -z": {"returncode": 0, "stdout": "", "stderr": ""},
            "git log --all --no-merges -n 40 "
            "--format=%x1e%h%x1f%aI%x1f%s%x1f%D --numstat":
                {"returncode": 0, "stdout": "", "stderr": ""},
        }

    def test_issues_failing_while_prs_succeed_is_reported_not_swallowed(self):
        # The regression guard for Finding 1: without separate statuses, a failing
        # `gh issue list` next to a succeeding `gh pr list` reads as "issues: ok".
        runner = ReplayRunner(self._recordings(
            pr_result={"returncode": 0, "stdout": "[]", "stderr": ""},
            issue_result={"returncode": 1, "stdout": "", "stderr": "HTTP 500: server error\n"},
        ))
        snapshot = collect(runner, "/repo", tempfile.mkdtemp())
        sources = {s["name"]: s for s in snapshot["repos"][0]["sources"]}
        self.assertTrue(sources["gh:prs"]["ok"])
        self.assertFalse(sources["gh:issues"]["ok"])
        self.assertIsNotNone(sources["gh:issues"]["error"])

    def test_empty_state_directory_is_not_a_hooks_failure(self):
        runner = ReplayRunner(self._recordings(
            pr_result={"returncode": 0, "stdout": "[]", "stderr": ""},
            issue_result={"returncode": 0, "stdout": "[]", "stderr": ""},
        ))
        snapshot = collect(runner, "/repo", tempfile.mkdtemp())  # empty: no session files
        sources = {s["name"]: s for s in snapshot["repos"][0]["sources"]}
        self.assertTrue(sources["hooks"]["ok"])

    def test_guessed_default_branch_is_reported_not_swallowed(self):
        # The regression guard for Finding 2: a failed origin/HEAD lookup must not
        # silently masquerade as a resolved "main" with every source reporting ok.
        recordings = self._recordings(
            pr_result={"returncode": 0, "stdout": "[]", "stderr": ""},
            issue_result={"returncode": 0, "stdout": "[]", "stderr": ""},
        )
        recordings["git symbolic-ref --short refs/remotes/origin/HEAD"] = {
            "returncode": 128, "stdout": "", "stderr": "ref not set",
        }
        runner = ReplayRunner(recordings)
        snapshot = collect(runner, "/repo", tempfile.mkdtemp())
        repo = snapshot["repos"][0]
        self.assertEqual(repo["default_branch"], "main")
        sources = {s["name"]: s for s in repo["sources"]}
        self.assertFalse(sources["git:default-branch"]["ok"])
        self.assertIsNotNone(sources["git:default-branch"]["error"])


if __name__ == "__main__":
    unittest.main()
