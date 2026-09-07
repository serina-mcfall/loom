# tests/test_collect.py
import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from loom.gitsrc import Worktree
from loom.ghsrc import PullRequest
from loom.runner import ReplayRunner
from loom.collect import find_flags, reap, collect, SCHEMA_VERSION
from loom import cost as cost_mod

NOW = datetime(2026, 8, 3, 8, 0, 0, tzinfo=timezone.utc)


def pr(number, branch, url=None):
    return PullRequest(
        number=number, title="t", branch=branch, draft=False, review=None,
        checks="none", updated_at="2026-08-03T00:00:00Z",
        url=url or f"https://github.com/you/example/pull/{number}",
    )


class TestFindFlags(unittest.TestCase):
    def test_pr_whose_branch_has_no_worktree_is_an_orphan(self):
        trees = [Worktree("/t/a", "a", "feature-a", "h")]
        flags = find_flags(trees, [pr(56, "fix/other")], ["/t"], lambda d: ["a"])
        self.assertEqual([f["kind"] for f in flags], ["orphan_pr"])
        self.assertIn("56", flags[0]["subject"])

    def test_pr_with_a_worktree_is_not_flagged(self):
        trees = [Worktree("/t/a", "a", "feature-a", "h")]
        self.assertEqual(find_flags(trees, [pr(1, "feature-a")], ["/t"], lambda d: ["a"]), [])

    def test_directory_that_is_not_a_worktree_is_stale(self):
        trees = [Worktree("/t/a", "a", "feature-a", "h")]
        flags = find_flags(trees, [], ["/t"], lambda d: ["a", "leftover"], lambda p: True)
        self.assertEqual([f["kind"] for f in flags], ["stale_dir"])
        self.assertIn("leftover", flags[0]["subject"])

    # ------------------------------------------------- audit 2026-08-05, M3
    def test_worktrees_spanning_two_parents_are_both_scanned(self):
        """`_worktree_parent` returned None unless EXACTLY one parent was found, and
        `find_flags` skipped the whole stale-directory scan when it was None.

        So a fleet whose worktrees live in two sibling directories -- or one worktree
        placed somewhere else -- lost stale-directory detection entirely, with no
        flag and no entry in `sources`. Absence of a warning reads as absence of a
        problem. The design doc's own grounding observations list "1 directory left
        behind that was no longer a git worktree" as a motivating fact.
        """
        trees = [Worktree("/t/one/a", "a", "fa", "h"),
                 Worktree("/t/two/b", "b", "fb", "h")]

        def listdir(d):
            return {"/t/one": ["a", "leftover-one"],
                    "/t/two": ["b", "leftover-two"]}.get(d, [])

        flags = find_flags(trees, [], ["/t/one", "/t/two"], listdir, lambda p: True)
        self.assertEqual(sorted(f["subject"] for f in flags),
                         ["leftover-one", "leftover-two"])

    def test_every_parent_directory_of_a_worktree_is_discovered(self):
        from loom.collect import _worktree_parents
        trees = [Worktree("/t/one/a", "a", "fa", "h"),
                 Worktree("/t/two/b", "b", "fb", "h")]
        self.assertEqual(_worktree_parents(trees, "/repo/root"), ["/t/one", "/t/two"])

    def test_the_repos_own_parent_is_not_scanned_as_a_worktree_parent(self):
        # The main checkout sits beside its siblings under ~/Launchpad; scanning
        # there would flag every unrelated project as a stale directory.
        from loom.collect import _worktree_parents
        trees = [Worktree("/home/x/Launchpad/loom", "loom", "main", "h")]
        self.assertEqual(_worktree_parents(trees, "/home/x/Launchpad/loom"), [])

    def test_a_tidy_fleet_produces_no_flags(self):
        # The negative control: this must be able to return nothing.
        trees = [Worktree("/t/a", "a", "feature-a", "h")]
        self.assertEqual(find_flags(trees, [pr(1, "feature-a")], ["/t"], lambda d: ["a"]), [])

    def test_hidden_directories_are_ignored(self):
        trees = [Worktree("/t/a", "a", "feature-a", "h")]
        self.assertEqual(find_flags(trees, [], ["/t"], lambda d: ["a", ".workmux_trash_x"]), [])

    def test_a_plain_file_is_not_flagged(self):
        trees = [Worktree("/t/a", "a", "feature-a", "h")]

        def listdir(d):
            return ["a", "notes.txt"] if d == "/t" else []

        def isdir(p):
            return p == "/t/a"  # notes.txt is a file, not a directory

        self.assertEqual(find_flags(trees, [], ["/t"], listdir, isdir), [])

    def test_a_directory_containing_dot_git_is_someone_elses_checkout_not_stale(self):
        trees = [Worktree("/t/a", "a", "feature-a", "h")]

        def listdir(d):
            if d == "/t":
                return ["a", "other-repo"]
            if d == "/t/other-repo":
                return [".git", "README.md"]
            return []

        self.assertEqual(find_flags(trees, [], ["/t"], listdir, lambda p: True), [])

    def test_a_directory_with_no_dot_git_is_still_flagged(self):
        # Positive control: the isdir/.git guard must not disable detection entirely.
        trees = [Worktree("/t/a", "a", "feature-a", "h")]

        def listdir(d):
            if d == "/t":
                return ["a", "leftover"]
            if d == "/t/leftover":
                return ["README.md"]
            return []

        flags = find_flags(trees, [], ["/t"], listdir, lambda p: True)
        self.assertEqual([f["kind"] for f in flags], ["stale_dir"])
        self.assertIn("leftover", flags[0]["subject"])


class TestSubprocessBudget(unittest.TestCase):
    """Audit 2026-08-05, finding M4.

    Loom is meant to sit open all day on a laptop, refreshing every 2 seconds. One
    tick used to spawn 12 processes for a SINGLE worktree -- 360 a minute -- and the
    cost is `5 + 7n`, so the six-worktree fleet the design was built against came to
    47 per tick and roughly 1,410 a minute.

    This test is a budget, deliberately: a bare count with the breakdown written
    down, so anyone adding a git call to the per-worktree path has to come here and
    justify raising it rather than quietly costing every user another 30 spawns a
    minute.
    """

    # Per tick, include_gh=False, one worktree:
    #   repo-level   default_branch, worktree list, tmux, origin remote,
    #                recent_commits, remote_reachable_shas               = 6
    #   per worktree rev-list (ahead/behind), status (counts AND paths),
    #                merge-base, diff merge-base..HEAD                     = 4
    #
    # `remote_reachable_shas` raised this from 5 to 6 (BUDGET 9 -> 10),
    # 2026-09-07, closing the interactivity spec's known "commit links can
    # 404 for unpushed commits" gap -- justified here per this test's own
    # rule, not slipped in silently. It is ONE call for the WHOLE commit
    # batch (never per-commit -- the per-commit alternative, `git
    # merge-base --is-ancestor` x40, was rejected specifically because of
    # this budget), and only runs at all when recent_commits() found at
    # least one commit -- a repo-level cost, not `7n`, so it does not
    # multiply with worktree count.
    BUDGET = 10

    def _runner(self):
        return ReplayRunner({
            "git symbolic-ref --short refs/remotes/origin/HEAD":
                {"returncode": 0, "stdout": "origin/main\n", "stderr": ""},
            "git worktree list --porcelain": {
                "returncode": 0,
                "stdout": "worktree /repo\nHEAD abc123\nbranch refs/heads/main\n\n",
                "stderr": ""},
            "tmux list-panes -a -F #{pane_current_path}\t#{pane_current_command}\t"
            "#{pane_pid}\t#{window_name}":
                {"returncode": 1, "stdout": "", "stderr": "no server"},
            "git rev-list --left-right --count main...HEAD":
                {"returncode": 0, "stdout": "0\t0\n", "stderr": ""},
            "git status --porcelain=v1 -z -uall": {"returncode": 0, "stdout": "", "stderr": ""},
            "git remote get-url origin":
                {"returncode": 0, "stdout": "git@github.com:you/example.git\n", "stderr": ""},
            "git merge-base main HEAD": {"returncode": 0, "stdout": "base1\n", "stderr": ""},
            "git diff --name-only -z base1 HEAD":
                {"returncode": 0, "stdout": "", "stderr": ""},
            "git log --all --no-merges -n 40 "
            "--format=%x1e%h%x1f%aI%x1f%s%x1f%D --numstat": {
                "returncode": 0,
                "stdout": ("\x1e161948b\x1f2026-08-03T07:31:55+12:00\x1f"
                           "a commit, so the budget exercises the real path\x1fHEAD -> main\n"
                           "1\t0\tREADME.md\n"),
                "stderr": "",
            },
            "git rev-list --remotes=origin/* --since-as-filter 2026-07-27T07:31:55+12:00":
                {"returncode": 0, "stdout": "161948bfeedfacecafebeef0123456789abcdef\n",
                 "stderr": ""},
        })

    def test_one_tick_over_one_worktree_stays_within_budget(self):
        runner = self._runner()
        collect(runner, "/repo", "/nonexistent-state-dir", include_gh=False)
        self.assertLessEqual(
            len(runner.calls), self.BUDGET,
            f"spawned {len(runner.calls)} processes, budget is {self.BUDGET}:\n" +
            "\n".join("    " + " ".join(c) for c in runner.calls))

    def test_the_status_call_is_not_repeated_per_worktree(self):
        # The specific saving: `git status` is asked ONCE and its answer feeds both
        # the dirty counts and the collisions path set.
        runner = self._runner()
        collect(runner, "/repo", "/nonexistent-state-dir", include_gh=False)
        statuses = [c for c in runner.calls if c[:2] == ("git", "status")]
        self.assertEqual(len(statuses), 1, f"status called {len(statuses)} times")

    def test_no_per_worktree_git_log_is_issued(self):
        # `_last_commit` cost one `git log` per worktree per tick to populate a field
        # no consumer read (audit L2). Removed rather than left as a silent tax.
        runner = self._runner()
        collect(runner, "/repo", "/nonexistent-state-dir", include_gh=False)
        per_tree_logs = [c for c in runner.calls if c[:3] == ("git", "log", "-1")]
        self.assertEqual(per_tree_logs, [])


class TestSchema(unittest.TestCase):
    def test_version_is_pinned(self):
        """Bumped to 2 on 2026-08-05 when three fields were removed from the contract.

        This test exists to make a bump DELIBERATE, and it did its job: the removals
        (worktree `head`, PR `worktree`, issue `assignees`) were read by no consumer,
        so nothing broke -- but "probably nobody noticed" is how a version field
        becomes decoration. Audit finding L2.
        """
        self.assertEqual(SCHEMA_VERSION, 2)


class TestDroppedFields(unittest.TestCase):
    """Audit 2026-08-05, finding L2.

    Fifteen fields were produced and read by nothing. Each was resolved as render,
    validate, or drop -- these are the drops: no consumer read them and none plausibly
    would, so they were pure schema noise and drift surface.

    `root` and `worktrees[].path` were deliberately KEPT despite also being unrendered.
    They are skill-facing: an agent reporting "worktree X needs you" has to be able to
    say where X is. That is now written down in the contract rather than left for
    someone to rediscover as apparently-dead weight.
    """

    def _snapshot(self):
        runner = TestSubprocessBudget()._runner()
        return collect(runner, "/repo", "/nonexistent-state-dir", include_gh=False)

    def test_a_worktree_no_longer_carries_its_head_sha(self):
        # The commits ticker already shows shas, and an eighth column in the
        # Worktrees table costs more than the field is worth.
        wt = self._snapshot()["repos"][0]["worktrees"][0]
        self.assertNotIn("head", wt)

    def test_a_worktree_still_carries_the_fields_the_page_renders(self):
        # Positive control: the drop must not have taken anything live with it.
        wt = self._snapshot()["repos"][0]["worktrees"][0]
        for k in ("dir", "path", "branch", "ahead", "behind", "dirty", "agent", "pr"):
            self.assertIn(k, wt)

    def test_the_repo_still_carries_the_skill_facing_paths(self):
        repo = self._snapshot()["repos"][0]
        self.assertIn("root", repo)


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
            "git status --porcelain=v1 -z -uall": {"returncode": 0, "stdout": "", "stderr": ""},
            "git remote get-url origin":
                {"returncode": 0, "stdout": "git@github.com:you/example.git\n", "stderr": ""},
            "gh pr list -R you/example --state open --limit 50 --json "
            "number,title,headRefName,isDraft,reviewDecision,statusCheckRollup,updatedAt,url": pr_result,
            "gh issue list -R you/example --state open --limit 50 --json "
            "number,title,labels,assignees,url": issue_result,
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

    def test_a_worktree_whose_branch_matches_a_pr_gets_the_real_pr_url(self):
        # The interactivity spec's worktree-badge link: pr_url must be the
        # SAME real gh-provided url the PRs & Issues panel uses, not a
        # separately constructed string -- proves by_branch's widening from
        # {branch: number} to {branch: PullRequest} actually reuses the
        # object rather than just re-deriving the number from it. The url
        # below is deliberately NOT what a naive f"https://github.com/
        # {issue_repo}/pull/{number}" reconstruction from "you/example"
        # (this fixture's real origin) and 42 would produce -- an earlier
        # version used a url matching that exact pattern, so a regression
        # that silently reconstructed instead of reusing would have passed
        # unnoticed. Found by an independent codex review, 2026-09-07.
        real_url = "https://github.com/a-totally-different-org/renamed-repo/pull/999?tab=files"
        pr_json = json.dumps([{
            "number": 42, "title": "t", "headRefName": "main",
            "isDraft": False, "reviewDecision": None, "statusCheckRollup": [],
            "updatedAt": "", "url": real_url,
        }])
        runner = ReplayRunner(self._recordings(
            pr_result={"returncode": 0, "stdout": pr_json, "stderr": ""},
            issue_result={"returncode": 0, "stdout": "[]", "stderr": ""},
        ))
        snapshot = collect(runner, "/repo", tempfile.mkdtemp())
        wt = snapshot["repos"][0]["worktrees"][0]
        self.assertEqual(wt["pr"], 42)
        self.assertEqual(wt["pr_url"], real_url)

    def test_reachable_and_unreachable_commits_in_the_same_batch_are_told_apart(self):
        # git has no notion of GitHub, so this is the one link that is BUILT
        # (issue_repo + sha), never fetched -- proves collect() actually
        # wires ghsrc.commit_url() in, using the real captured git-log
        # fixture shape from tests/test_gitsrc.py (LOG) rather than a
        # hand-rolled one that could diverge from the real numstat format.
        #
        # TWO commits in ONE batch, one reachable and one not, against a
        # rev-list result that is neither empty nor "everything matches" --
        # found by an independent codex review, 2026-09-07: a first draft's
        # tests used a single-commit batch, so `commit_reachable()` could
        # have been replaced with `bool(remote_shas)` (or reachability moved
        # inside the loop, one call per commit) and every test still
        # passed. This shape rules out both: the decoy sha in rev-list's
        # output proves the list is genuinely non-empty without containing
        # the unreachable commit, and the call-count assertion below proves
        # exactly one rev-list call covers the whole batch.
        #
        # CORRECTED (found by review-tests, confirmed by review-adjudicate,
        # 2026-09-07): the decoy above was neither a prefix NOR a substring
        # of the unreachable sha, so `full.startswith(sha)` (correct) and a
        # regressed `sha in full` (wrong -- would match ANY sha appearing
        # anywhere inside a full sha, not just as its prefix) produced
        # identical results here. The third decoy below embeds the
        # unreachable sha's digits mid-string, not at position 0, so only
        # the correct prefix-match semantics pass this test.
        recordings = self._recordings(
            pr_result={"returncode": 0, "stdout": "[]", "stderr": ""},
            issue_result={"returncode": 0, "stdout": "[]", "stderr": ""},
        )
        recordings["git log --all --no-merges -n 40 "
                   "--format=%x1e%h%x1f%aI%x1f%s%x1f%D --numstat"] = {
            "returncode": 0,
            "stdout": ("\x1e161948b\x1f2026-08-03T07:31:55+12:00\x1f"
                       "pushed to origin\x1fHEAD -> feature-c\n"
                       "3\t1\tsrc/board.ts\n"
                       "\x1e2ee9911\x1f2026-08-02T10:00:00+12:00\x1f"
                       "never pushed anywhere\x1fHEAD -> feature-c\n"
                       "1\t0\tsrc/other.ts\n"),
            "stderr": "",
        }
        # min(when) is the 08-02 commit; SINCE_MARGIN (7 days) is subtracted
        # from it, giving this exact bound.
        recordings["git rev-list --remotes=origin/* --since-as-filter 2026-07-26T10:00:00+12:00"] = {
            "returncode": 0,
            # A decoy full sha that is neither commit -- proves membership
            # is genuinely checked, not "list has something in it". A THIRD
            # decoy embeds the unreachable commit's abbreviated sha mid-string
            # (not at position 0) -- proves membership is a PREFIX match, not
            # a substring match: a regressed `sha in full` would wrongly call
            # "2ee9911" reachable via this line, while `full.startswith(sha)`
            # correctly does not.
            "stdout": ("161948bfeedfacecafebeef0123456789abcdef\n"
                       "deadbeef00000000000000000000000000000000\n"
                       "aaaaaaaa2ee9911bbbbbbbbbbbbbbbbbbbbbbbbbb\n"),
            "stderr": "",
        }
        runner = ReplayRunner(recordings)
        snapshot = collect(runner, "/repo", tempfile.mkdtemp())
        commits = {c["sha"]: c for c in snapshot["repos"][0]["commits"]}
        self.assertEqual(commits["161948b"]["url"],
                          "https://github.com/you/example/commit/161948b")
        self.assertIsNone(commits["2ee9911"]["url"])
        rev_list_calls = [c for c in runner.calls if c[:2] == ("git", "rev-list")
                          and "--remotes=origin/*" in c]
        self.assertEqual(len(rev_list_calls), 1,
                          f"expected exactly one batched reachability call, got "
                          f"{len(rev_list_calls)}: {rev_list_calls}")

    def test_a_failed_reachability_check_also_withholds_the_url(self):
        # Same honesty rule the rest of this project follows: a git call
        # that fails must never be read as "checked and it's fine". If
        # `git rev-list --remotes` itself fails, no commit gets a url,
        # not every commit.
        recordings = self._recordings(
            pr_result={"returncode": 0, "stdout": "[]", "stderr": ""},
            issue_result={"returncode": 0, "stdout": "[]", "stderr": ""},
        )
        recordings["git log --all --no-merges -n 40 "
                   "--format=%x1e%h%x1f%aI%x1f%s%x1f%D --numstat"] = {
            "returncode": 0,
            "stdout": ("\x1e161948b\x1f2026-08-03T07:31:55+12:00\x1f"
                       "test(clues): flatten\x1fHEAD -> feature-c\n"
                       "3\t1\tsrc/board.ts\n"),
            "stderr": "",
        }
        recordings["git rev-list --remotes=origin/* --since-as-filter 2026-07-27T07:31:55+12:00"] = {
            "returncode": 128, "stdout": "", "stderr": "fatal: bad revision",
        }
        runner = ReplayRunner(recordings)
        snapshot = collect(runner, "/repo", tempfile.mkdtemp())
        commit = snapshot["repos"][0]["commits"][0]
        self.assertIsNone(commit["url"])

    def test_a_repo_with_no_github_remote_skips_the_reachability_call_entirely(self):
        # Found by review-code, confirmed by review-adjudicate, 2026-09-07: a
        # repo with real commit history but no GitHub-shaped origin (a GitLab/
        # Bitbucket remote, or none at all) used to pay one `git rev-list`
        # subprocess call every tick for a `commit_url` that can NEVER be
        # produced without a GitHub repo to point at -- independent of whether
        # any commit is actually reachable. `ReplayRunner` raises on any
        # unrecorded call, so simply not recording `git rev-list --remotes=
        # origin/*` here is itself the proof the call never happens.
        recordings = self._recordings(
            pr_result={"returncode": 0, "stdout": "[]", "stderr": ""},
            issue_result={"returncode": 0, "stdout": "[]", "stderr": ""},
        )
        recordings["git remote get-url origin"] = {
            "returncode": 0, "stdout": "git@gitlab.com:you/example.git\n", "stderr": "",
        }
        # gh calls are keyed on "-R you/example" regardless of origin_repo, so
        # the PR/issue fixtures above still apply unchanged.
        recordings["git log --all --no-merges -n 40 "
                   "--format=%x1e%h%x1f%aI%x1f%s%x1f%D --numstat"] = {
            "returncode": 0,
            "stdout": ("\x1e161948b\x1f2026-08-03T07:31:55+12:00\x1f"
                       "pushed to origin\x1fHEAD -> feature-c\n"
                       "3\t1\tsrc/board.ts\n"),
            "stderr": "",
        }
        runner = ReplayRunner(recordings)
        snapshot = collect(runner, "/repo", tempfile.mkdtemp())
        commit = snapshot["repos"][0]["commits"][0]
        self.assertIsNone(commit["url"])

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


def _single_worktree_recordings(worktree_stdout: str) -> dict:
    """The full recording set collect() needs for `include_gh=False` over
    whatever worktree(s) `worktree_stdout` describes. Every per-worktree git
    command is keyed on its argv alone (loom/runner.py's ReplayRunner), never
    on cwd, so the SAME entry answers for every worktree in the fixture.
    """
    return {
        "git symbolic-ref --short refs/remotes/origin/HEAD":
            {"returncode": 0, "stdout": "origin/main\n", "stderr": ""},
        "git worktree list --porcelain":
            {"returncode": 0, "stdout": worktree_stdout, "stderr": ""},
        "tmux list-panes -a -F #{pane_current_path}\t#{pane_current_command}\t"
        "#{pane_pid}\t#{window_name}":
            {"returncode": 1, "stdout": "", "stderr": "no server"},
        "git rev-list --left-right --count main...HEAD":
            {"returncode": 0, "stdout": "0\t0\n", "stderr": ""},
        "git status --porcelain=v1 -z -uall": {"returncode": 0, "stdout": "", "stderr": ""},
        "git remote get-url origin":
            {"returncode": 0, "stdout": "git@github.com:you/example.git\n", "stderr": ""},
        "git merge-base main HEAD": {"returncode": 0, "stdout": "base1\n", "stderr": ""},
        "git diff --name-only -z base1 HEAD": {"returncode": 0, "stdout": "", "stderr": ""},
        "git log --all --no-merges -n 40 "
        "--format=%x1e%h%x1f%aI%x1f%s%x1f%D --numstat":
            {"returncode": 0, "stdout": "", "stderr": ""},
    }


class TestCollectCost(unittest.TestCase):
    """Step 5: worktree_cost wired into collect(), under the real caller
    (never a planted call to worktree_cost directly), so a wiring mistake at
    the call site is exactly what these can catch.
    """

    def setUp(self):
        cost_mod.reset_cache()

    def tearDown(self):
        cost_mod.reset_cache()

    def test_second_tick_over_an_unchanged_transcript_does_not_reparse(self):
        # `collect()` is exactly what `loom serve`'s refresh loop calls every
        # FAST_SECONDS -- calling it twice here exercises the real path a
        # CLI-only, one-shot check structurally cannot see.
        state_dir = tempfile.mkdtemp()
        Path(state_dir, "s1.json").write_text(json.dumps(
            {"session_id": "s1", "cwd": "/repo", "state": "idle",
             "since": datetime.now(timezone.utc).isoformat(), "pid": 1}))
        home = tempfile.mkdtemp()
        slug_dir = Path(home, ".claude", "projects", "-repo")
        slug_dir.mkdir(parents=True)
        (slug_dir / "s1.jsonl").write_text(json.dumps(
            {"message": {"model": "claude-opus-5",
                        "usage": {"input_tokens": 0, "output_tokens": 1_000,
                                 "cache_read_input_tokens": 0,
                                 "cache_creation": {"ephemeral_5m_input_tokens": 0,
                                                    "ephemeral_1h_input_tokens": 0}}}}) + "\n")
        worktree_stdout = "worktree /repo\nHEAD abc123\nbranch refs/heads/main\n\n"

        with patch.object(cost_mod, "DEFAULT_HOME", home), \
             patch.object(cost_mod, "read_usage", wraps=cost_mod.read_usage) as spy:
            runner = ReplayRunner(_single_worktree_recordings(worktree_stdout))
            first = collect(runner, "/repo", state_dir, include_gh=False)
            second = collect(runner, "/repo", state_dir, include_gh=False)

        self.assertEqual(spy.call_count, 1,
                         "an unchanged transcript's second tick must cost a "
                         "stat, not a re-parse")
        self.assertEqual(
            first["repos"][0]["worktrees"][0]["cost"]["tokens"]["output"], 1_000)
        self.assertEqual(
            second["repos"][0]["worktrees"][0]["cost"]["tokens"]["output"], 1_000)

    def test_unreadable_cost_names_the_worktree_directory_in_the_source(self):
        state_dir = tempfile.mkdtemp()
        Path(state_dir, "s1.json").write_text(json.dumps(
            {"session_id": "s1", "cwd": "/repo", "state": "idle",
             "since": datetime.now(timezone.utc).isoformat(), "pid": 1}))
        home = tempfile.mkdtemp()
        slug_dir = Path(home, ".claude", "projects", "-repo")
        slug_dir.mkdir(parents=True)
        transcript = slug_dir / "s1.jsonl"
        transcript.write_text(json.dumps(
            {"message": {"model": "claude-opus-5",
                        "usage": {"input_tokens": 1, "output_tokens": 1,
                                 "cache_read_input_tokens": 0,
                                 "cache_creation": {"ephemeral_5m_input_tokens": 0,
                                                    "ephemeral_1h_input_tokens": 0}}}}) + "\n")
        os.chmod(transcript, 0o000)
        worktree_stdout = "worktree /repo\nHEAD abc123\nbranch refs/heads/main\n\n"
        try:
            with patch.object(cost_mod, "DEFAULT_HOME", home):
                runner = ReplayRunner(_single_worktree_recordings(worktree_stdout))
                snapshot = collect(runner, "/repo", state_dir, include_gh=False)
        finally:
            os.chmod(transcript, 0o644)

        sources = {s["name"]: s for s in snapshot["repos"][0]["sources"]}
        self.assertFalse(sources["cost"]["ok"])
        self.assertIsNotNone(sources["cost"]["error"])
        self.assertIn("repo", sources["cost"]["error"],
                      "the message must name the affected worktree directory, "
                      "not a bare ok=False")

    def test_nested_worktree_pair_gets_the_full_sibling_list_through_collect(self):
        # Mirrors step 4's own nested-worktree fixture, but through the REAL
        # collect() call site -- the one fixture that catches a wiring
        # mistake (a partial sibling list passed at the call site) that step
        # 4's own unit-level fixture cannot see, because that fixture calls
        # worktree_cost directly with sibling_paths already correct.
        parent = "/repo"
        nested = "/repo/__worktrees/a"
        worktree_stdout = (
            f"worktree {parent}\nHEAD abc123\nbranch refs/heads/main\n\n"
            f"worktree {nested}\nHEAD def456\nbranch refs/heads/feature-a\n\n"
        )
        state_dir = tempfile.mkdtemp()
        now_iso = datetime.now(timezone.utc).isoformat()
        Path(state_dir, "s-parent.json").write_text(json.dumps(
            {"session_id": "s-parent", "cwd": parent, "state": "idle",
             "since": now_iso, "pid": 1}))
        Path(state_dir, "s-nested.json").write_text(json.dumps(
            {"session_id": "s-nested", "cwd": nested, "state": "idle",
             "since": now_iso, "pid": 2}))

        home = tempfile.mkdtemp()

        def write_transcript(cwd, session_id, output_tokens):
            import re
            slug = re.sub(r"[^a-zA-Z0-9]", "-", cwd)
            d = Path(home, ".claude", "projects", slug)
            d.mkdir(parents=True)
            line = json.dumps({"message": {"model": "claude-opus-5",
                                           "usage": {"input_tokens": 0,
                                                    "output_tokens": output_tokens,
                                                    "cache_read_input_tokens": 0,
                                                    "cache_creation": {
                                                        "ephemeral_5m_input_tokens": 0,
                                                        "ephemeral_1h_input_tokens": 0}}}})
            (d / f"{session_id}.jsonl").write_text(line + "\n")

        write_transcript(parent, "s-parent", 1_000)
        write_transcript(nested, "s-nested", 9_000)

        with patch.object(cost_mod, "DEFAULT_HOME", home):
            runner = ReplayRunner(_single_worktree_recordings(worktree_stdout))
            snapshot = collect(runner, "/repo", state_dir, include_gh=False)

        by_dir = {w["dir"]: w for w in snapshot["repos"][0]["worktrees"]}
        # Each worktree's own session count, not the total -- if collect()
        # passed a partial sibling list, the parent's sum would absorb the
        # nested worktree's tokens too (1_000 + 9_000), the exact
        # double-counting step 4's nearest-enclosing rule exists to prevent.
        self.assertEqual(by_dir["repo"]["cost"]["tokens"]["output"], 1_000)
        self.assertEqual(by_dir["a"]["cost"]["tokens"]["output"], 9_000)


if __name__ == "__main__":
    unittest.main()
