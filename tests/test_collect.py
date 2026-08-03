# tests/test_collect.py
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
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

    def test_include_gh_false_issues_no_gh_command_and_reports_not_fetched(self):
        # The regression guard for the caller who forgets to substitute cached data:
        # skipping gh must be an honest "not fetched", never a silent "0 PRs".
        recordings = self._recordings(
            pr_result={"returncode": 0, "stdout": "[]", "stderr": ""},
            issue_result={"returncode": 0, "stdout": "[]", "stderr": ""},
        )
        runner = ReplayRunner(recordings)
        snapshot = collect(runner, "/repo", tempfile.mkdtemp(), include_gh=False)
        repo = snapshot["repos"][0]

        self.assertEqual(repo["prs"], [])
        self.assertEqual(repo["issues"], [])

        sources = {s["name"]: s for s in repo["sources"]}
        self.assertFalse(sources["gh:prs"]["ok"])
        self.assertEqual(sources["gh:prs"]["error"], "not fetched this cycle")
        self.assertFalse(sources["gh:issues"]["ok"])
        self.assertEqual(sources["gh:issues"]["error"], "not fetched this cycle")

        self.assertFalse(any(c[0] == "gh" for c in runner.calls))

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




class TestCollectPassesARealClock(unittest.TestCase):
    """The clock `collect()` hands to agent_for was untested, and it decides
    every staleness verdict in the snapshot.

    Found by review: replacing it with `datetime(1970,1,1)` passed all 189 tests,
    which means nothing is ever stale and a dead agent reports `working` forever
    — the forbidden direction, invisible to the suite. Replacing it with
    `datetime(3000,1,1)` also passed, meaning everything is always stale. Both
    survived because every other collect() test uses an EMPTY state directory,
    so no test had ever run collect() with a session file on disk.

    These tests read the resulting `agent` block, so a wrong clock cannot pass.
    """

    def _state_dir(self, state, since):
        d = tempfile.mkdtemp()
        Path(d, "s1.json").write_text(json.dumps(
            {"session_id": "s1", "cwd": "/repo", "state": state,
             "since": since, "pid": 1}))
        return d

    def _snapshot(self, state, since):
        # Reuses TestCollectSources' recordings so this stays a REAL collect()
        # call end to end — the point is the clock it passes through, and a
        # hand-rolled runner could diverge from the shape collect() drives.
        rec = TestCollectSources._recordings(
            self,
            pr_result={"returncode": 0, "stdout": "[]", "stderr": ""},
            issue_result={"returncode": 0, "stdout": "[]", "stderr": ""},
        )
        return collect(ReplayRunner(rec), "/repo",
                       self._state_dir(state, since), include_gh=True)

    def _agent(self, snapshot):
        trees = snapshot["repos"][0]["worktrees"]
        # The fixture's worktree is /repo itself.
        return next(t["agent"] for t in trees if t["path"] == "/repo")

    def test_a_fresh_working_session_survives_collect(self):
        # A wall-clock far in the past would stale nothing; far in the future
        # would stale everything. This pins the near end.
        fresh = (datetime.now(timezone.utc).astimezone() - timedelta(seconds=5)).isoformat()
        a = self._agent(self._snapshot("working", fresh))
        self.assertEqual(a["state"], "working")
        self.assertIsNotNone(a["age_seconds"])
        self.assertLess(a["age_seconds"], 60, "a 5s-old record must read as seconds old")

    def test_an_ancient_working_session_is_staled_by_collect(self):
        # And this pins the far end. Together they bracket the clock: it must be
        # roughly now, not 1970 and not 3000.
        old = (datetime.now(timezone.utc).astimezone() - timedelta(days=2)).isoformat()
        a = self._agent(self._snapshot("working", old))
        self.assertEqual(a["state"], "stale")

    # A third test asserting "the clock is timezone-aware" was written here and
    # DELETED after review. Its body was byte-identical to the test above, and it
    # could never have done what its name claimed: `collect()` computes `now`
    # internally, so no test at this layer can hand it a naive clock. It detected
    # nothing the test above does not — with it removed, all three clock mutations
    # still failed. It was a false coverage claim, the ninth instance of that
    # pattern in this project and the first written by the author of the fix it
    # was meant to guard.
    #
    # The naive-clock case IS covered, one layer down, where a clock can actually
    # be injected: tests/test_agents.py::test_a_naive_CLOCK_does_not_crash_the_snapshot.


if __name__ == "__main__":
    unittest.main()
