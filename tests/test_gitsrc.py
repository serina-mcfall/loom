import unittest
from loom.runner import ReplayRunner
from loom.gitsrc import (list_worktrees, ahead_behind, Dirty, recent_commits,
                          touched_files, collisions, Worktree, default_branch,
                          Status)

PORCELAIN = (
    "worktree /repo\n"
    "HEAD 38e0a43c6bfa8f9350911bb08c806faf9b70c551\n"
    "branch refs/heads/main\n"
    "\n"
    "worktree /trees/feature-a\n"
    "HEAD 161948b0000000000000000000000000000000aa\n"
    "branch refs/heads/feature-a\n"
    "\n"
    "worktree /trees/detached\n"
    "HEAD aaaabbbb0000000000000000000000000000cccc\n"
    "detached\n"
)


class TestListWorktrees(unittest.TestCase):
    def setUp(self):
        self.runner = ReplayRunner({
            "git worktree list --porcelain": {"returncode": 0, "stdout": PORCELAIN, "stderr": ""},
        })

    def test_parses_every_worktree(self):
        trees = list_worktrees(self.runner, "/repo")
        self.assertEqual([t.dir for t in trees], ["repo", "feature-a", "detached"])

    def test_branch_is_stripped_of_refs_heads(self):
        trees = list_worktrees(self.runner, "/repo")
        self.assertEqual(trees[1].branch, "feature-a")

    def test_detached_head_has_no_branch(self):
        trees = list_worktrees(self.runner, "/repo")
        self.assertIsNone(trees[2].branch)

    def test_failure_returns_empty_and_does_not_raise(self):
        runner = ReplayRunner({
            "git worktree list --porcelain": {"returncode": 128, "stdout": "", "stderr": "not a repo"},
        })
        self.assertEqual(list_worktrees(runner, "/repo"), [])


class TestDefaultBranch(unittest.TestCase):
    def test_resolves_the_branch_from_origin_head(self):
        runner = ReplayRunner({
            "git symbolic-ref --short refs/remotes/origin/HEAD":
                {"returncode": 0, "stdout": "origin/develop\n", "stderr": ""},
        })
        self.assertEqual(default_branch(runner, "/repo"), ("develop", True))

    def test_failure_falls_back_to_main_and_reports_unresolved(self):
        runner = ReplayRunner({
            "git symbolic-ref --short refs/remotes/origin/HEAD":
                {"returncode": 128, "stdout": "", "stderr": "ref not set"},
        })
        self.assertEqual(default_branch(runner, "/repo"), ("main", False))


class TestAheadBehind(unittest.TestCase):
    def test_left_is_behind_and_right_is_ahead(self):
        runner = ReplayRunner({
            "git rev-list --left-right --count main...HEAD":
                {"returncode": 0, "stdout": "10\t12\n", "stderr": ""},
        })
        self.assertEqual(ahead_behind(runner, "/trees/a", "main"), (12, 10))

    def test_failure_is_none_not_zero_zero(self):
        """Audit 2026-08-05, finding H3.

        This test previously asserted `(0, 0)` -- it was written to lock in the
        defect. A worktree 12 ahead whose `git rev-list` failed reported exactly
        what a worktree in perfect sync reports, and the page rendered "0".

        `None` means CANNOT TELL, exactly as `_age_seconds` in loom/agents.py
        already established for timestamps, and must never be read as zero.
        """
        runner = ReplayRunner({
            "git rev-list --left-right --count main...HEAD":
                {"returncode": 128, "stdout": "", "stderr": "bad revision"},
        })
        self.assertIsNone(ahead_behind(runner, "/trees/a", "main"))

    def test_unparseable_output_is_none_not_zero_zero(self):
        # git always prints two integers here, so anything else means the command
        # did not do what we think it did -- guessing zero would be a confident
        # wrong answer.
        runner = ReplayRunner({
            "git rev-list --left-right --count main...HEAD":
                {"returncode": 0, "stdout": "not numbers at all\n", "stderr": ""},
        })
        self.assertIsNone(ahead_behind(runner, "/trees/a", "main"))


LOG = (
    "\x1e161948b\x1f2026-08-03T07:31:55+12:00\x1ftest(clues): flatten\x1fHEAD -> feature-c\n"
    "3\t1\tsrc/board.ts\n"
    "10\t0\tsrc/clue.ts\n"
    "\x1eaaaa111\x1f2026-08-03T07:30:38+12:00\x1fCorrect the shell\x1fHEAD -> feature-b\n"
    "1\t1\tsrc/shell.ts\n"
)


class TestRecentCommits(unittest.TestCase):
    def setUp(self):
        self.runner = ReplayRunner({
            "git log --all --no-merges -n 40 "
            "--format=%x1e%h%x1f%aI%x1f%s%x1f%D --numstat":
                {"returncode": 0, "stdout": LOG, "stderr": ""},
        })

    def test_parses_each_commit_with_its_stats(self):
        commits = recent_commits(self.runner, "/repo")
        self.assertEqual(len(commits), 2)
        self.assertEqual(commits[0].sha, "161948b")
        self.assertEqual(commits[0].files, 2)
        self.assertEqual(commits[0].add, 13)
        self.assertEqual(commits[0].dele, 1)

    def test_branch_comes_from_the_decoration(self):
        self.assertEqual(recent_commits(self.runner, "/repo")[0].branch, "feature-c")


class TestWorktreeStatus(unittest.TestCase):
    """Audit 2026-08-05, finding M4.

    One `git status` call now yields BOTH the dirty counts and the set of changed
    paths. It used to take three separate calls to learn the same things: `git
    status` for the counts, then `git diff --name-only HEAD` and `git ls-files
    --others` inside `touched_files` for the paths -- all three asking the same
    working tree about the same changes.

    `-z` is required, not cosmetic: `--porcelain=v1` without it QUOTES paths
    containing spaces or non-ASCII, so a collisions matrix built from the parsed
    output would silently disagree with one built from `git diff -z`.
    """

    def _status(self, out: str):
        from loom.gitsrc import worktree_status
        return worktree_status(ReplayRunner({
            "git status --porcelain=v1 -z -uall": {"returncode": 0, "stdout": out, "stderr": ""},
        }), "/t/one")

    def test_counts_and_paths_come_from_the_same_single_call(self):
        s = self._status("M  staged.py\0 M unstaged.py\0?? new.py\0")
        self.assertEqual(s.dirty, Dirty(staged=1, unstaged=1, untracked=1))
        self.assertEqual(s.paths, {"staged.py", "unstaged.py", "new.py"})

    def test_a_file_both_staged_and_unstaged_counts_in_both_columns_once(self):
        """`MM` — staged AND further modified in the working tree.

        Inherited from the deleted `TestDirtyCounts`, which was the only place this
        case was covered. It matters because rank 5 sums the three columns: if `MM`
        counted once, a tree with staged-and-modified work would understate what is
        at risk, and if it counted as two files the total would overstate it.
        """
        s = self._status("M  staged.py\0 M unstaged.py\0MM both.py\0?? new.py\0")
        self.assertEqual(s.dirty, Dirty(staged=2, unstaged=2, untracked=1))
        self.assertEqual(s.paths, {"staged.py", "unstaged.py", "both.py", "new.py"})

    def test_a_rename_reports_the_new_path_and_consumes_the_old_one(self):
        """`R  new\\0old\\0` -- the ORIGINAL path is a separate NUL token.

        Verified against real git output. Miss this and the old path is parsed as
        though it were a status entry of its own, which corrupts every path after
        it in the stream.

        Only the new path is reported, matching `git diff --name-only`'s existing
        rename behaviour, so the two sources of collision paths agree.
        """
        s = self._status("R  renamed.txt\0a.txt\0 M b.txt\0")
        self.assertEqual(s.paths, {"renamed.txt", "b.txt"},
                         "the old path leaked in, or the stream desynchronised")
        self.assertEqual(s.dirty, Dirty(staged=1, unstaged=1, untracked=0))

    def test_a_path_with_a_space_survives_intact(self):
        # The reason -z is mandatory: without it git would quote this.
        s = self._status(" M some dir/a file.txt\0")
        self.assertEqual(s.paths, {"some dir/a file.txt"})

    def test_a_clean_tree_is_counts_of_zero_and_no_paths(self):
        s = self._status("")
        self.assertEqual(s.dirty, Dirty(0, 0, 0))
        self.assertEqual(s.paths, set())

    def test_a_failed_status_is_none_not_an_empty_status(self):
        from loom.gitsrc import worktree_status
        runner = ReplayRunner({
            "git status --porcelain=v1 -z -uall":
                {"returncode": 128, "stdout": "", "stderr": "not a work tree"},
        })
        self.assertIsNone(worktree_status(runner, "/t/one"))

    # ------------------------------------------------------------- issue #17
    def test_a_new_directory_with_several_files_reports_the_true_count(self):
        """Issue #17, Consequence 1 -- undercounting rank 5's dirty total.

        Real git output from a live repro: a brand-new directory holding three
        files collapses to one line naming the directory under the default
        `-unormal` (pre-fix, the OLD key), and expands to three specific
        filenames under `-uall` (post-fix, the key `worktree_status` now
        requests). Registering both keys on one runner means reverting step
        1's code change makes this fail on a real assertion (untracked=1, one
        collapsed path) rather than a KeyError.
        """
        from loom.gitsrc import worktree_status
        runner = ReplayRunner({
            "git status --porcelain=v1 -z":
                {"returncode": 0, "stdout": "?? newfeature/\0", "stderr": ""},
            "git status --porcelain=v1 -z -uall": {
                "returncode": 0,
                "stdout": "?? newfeature/one.ts\0?? newfeature/three.ts\0?? newfeature/two.ts\0",
                "stderr": "",
            },
        })
        s = worktree_status(runner, "/t/one")
        self.assertEqual(s.dirty, Dirty(staged=0, unstaged=0, untracked=3))
        self.assertEqual(s.paths, {"newfeature/one.ts", "newfeature/two.ts", "newfeature/three.ts"})

    def test_asymmetric_tracked_state_now_collides_through_the_real_matrix(self):
        """Issue #17, Consequence 2 -- the case ALREADY TRUE marks as "the one
        `-uall` is actually required for", verified live with two real git
        worktrees on divergent branches.

        Worktree A's `shared/` is already a tracked directory (committed
        earlier on its branch), so git reports the specific filename either
        way: `?? shared/thing.ts`. Worktree B's `shared/` was never committed
        at all, so the whole directory collapses under `-unormal` (`??
        shared/`) and only expands to the specific filename under `-uall`.
        Without `-uall` these are two different strings and no collision is
        detected even though both worktrees hold the identical uncommitted
        file.

        ReplayRunner keys on argv alone, not cwd (loom/runner.py:42-43), so
        one shared runner cannot give two worktrees two different outputs for
        the identical git-status command -- each worktree's Status is
        hand-built instead of derived through worktree_status().
        """
        status_a = Status(dirty=Dirty(untracked=1), paths=frozenset({"shared/thing.ts"}))
        status_b_post_fix = Status(dirty=Dirty(untracked=1), paths=frozenset({"shared/thing.ts"}))
        runner = ReplayRunner({
            "git merge-base main HEAD": {"returncode": 0, "stdout": "base1\n", "stderr": ""},
            "git diff --name-only -z base1 HEAD": {"returncode": 0, "stdout": "", "stderr": ""},
        })
        trees = [Worktree("/t/a", "a", "has-shared-dir", "ha"),
                 Worktree("/t/b", "b", "wt-b-fresh", "hb")]
        statuses = {"/t/a": status_a, "/t/b": status_b_post_fix}
        result, undetermined = collisions(runner, trees, "main", statuses)
        self.assertEqual([c["file"] for c in result], ["shared/thing.ts"])
        self.assertEqual(result[0]["branches"], ["has-shared-dir", "wt-b-fresh"])
        self.assertEqual(undetermined, [])

    def test_different_files_in_a_same_named_new_directory_do_not_collide(self):
        """The false-positive defect this plan's own live repro found, not in
        the issue: two worktrees each creating a brand-new SAME-NAMED
        directory but with DIFFERENT files inside must NOT collide. Real git
        output from a live repro: pre-fix both collapse to `?? shared/` (a
        false-positive collision on the directory name); post-fix each
        expands to its own real filename and the false positive is gone.
        """
        status_a = Status(dirty=Dirty(untracked=1), paths=frozenset({"shared/alpha.ts"}))
        status_b = Status(dirty=Dirty(untracked=1), paths=frozenset({"shared/beta.ts"}))
        runner = ReplayRunner({
            "git merge-base main HEAD": {"returncode": 0, "stdout": "base1\n", "stderr": ""},
            "git diff --name-only -z base1 HEAD": {"returncode": 0, "stdout": "", "stderr": ""},
        })
        trees = [Worktree("/t/a", "a", "a", "ha"), Worktree("/t/b", "b", "b", "hb")]
        statuses = {"/t/a": status_a, "/t/b": status_b}
        result, undetermined = collisions(runner, trees, "main", statuses)
        self.assertEqual(result, [])
        self.assertEqual(undetermined, [])


class TestCollisions(unittest.TestCase):
    def _runner(self):
        return ReplayRunner({
            "git merge-base main HEAD": {"returncode": 0, "stdout": "base1\n", "stderr": ""},
            "git diff --name-only -z base1 HEAD": {"returncode": 0, "stdout": "", "stderr": ""},
            "git diff --name-only -z HEAD": {"returncode": 0, "stdout": "", "stderr": ""},
            "git ls-files --others --exclude-standard -z": {"returncode": 0, "stdout": "", "stderr": ""},
        })

    def test_two_trees_touching_the_same_files_collide(self):
        runner = ReplayRunner({
            "git merge-base main HEAD": {"returncode": 0, "stdout": "base1\n", "stderr": ""},
            "git diff --name-only -z base1 HEAD": {"returncode": 0, "stdout": "src/a.ts\0", "stderr": ""},
            "git diff --name-only -z HEAD": {"returncode": 0, "stdout": "src/b.ts\0", "stderr": ""},
            "git ls-files --others --exclude-standard -z": {"returncode": 0, "stdout": "", "stderr": ""},
        })
        trees = [Worktree("/t/one", "one", "one", "h1"), Worktree("/t/two", "two", "two", "h2")]
        # ReplayRunner keys on argv alone, so both trees replay the same recording and
        # therefore both touch {a.ts, b.ts}. Positive control.
        result, undetermined = collisions(runner, trees, "main")
        self.assertEqual([c["file"] for c in result], ["src/a.ts", "src/b.ts"])
        self.assertEqual(result[0]["branches"], ["one", "two"])
        self.assertEqual(undetermined, [])

    def test_single_tree_never_collides_with_itself(self):
        runner = ReplayRunner({
            "git merge-base main HEAD": {"returncode": 0, "stdout": "base1\n", "stderr": ""},
            "git diff --name-only -z base1 HEAD": {"returncode": 0, "stdout": "src/a.ts\0", "stderr": ""},
            "git diff --name-only -z HEAD": {"returncode": 0, "stdout": "", "stderr": ""},
            "git ls-files --others --exclude-standard -z": {"returncode": 0, "stdout": "", "stderr": ""},
        })
        trees = [Worktree("/t/one", "one", "one", "h1")]
        self.assertEqual(collisions(runner, trees, "main"), ([], []))

    def test_touched_files_unions_committed_and_uncommitted(self):
        runner = ReplayRunner({
            "git merge-base main HEAD": {"returncode": 0, "stdout": "base1\n", "stderr": ""},
            "git diff --name-only -z base1 HEAD": {"returncode": 0, "stdout": "src/a.ts\0", "stderr": ""},
            "git diff --name-only -z HEAD": {"returncode": 0, "stdout": "", "stderr": ""},
            "git ls-files --others --exclude-standard -z": {"returncode": 0, "stdout": "src/new.ts\0", "stderr": ""},
        })
        self.assertEqual(touched_files(runner, "/t/one", "main"), {"src/a.ts", "src/new.ts"})

    def test_renames_appear_as_new_path_only(self):
        runner = ReplayRunner({
            "git merge-base main HEAD": {"returncode": 0, "stdout": "base1\n", "stderr": ""},
            "git diff --name-only -z base1 HEAD": {"returncode": 0, "stdout": "new.ts\0", "stderr": ""},
            "git diff --name-only -z HEAD": {"returncode": 0, "stdout": "", "stderr": ""},
            "git ls-files --others --exclude-standard -z": {"returncode": 0, "stdout": "", "stderr": ""},
        })
        # Git's --name-only applies rename detection by default and reports only the new path.
        result = touched_files(runner, "/t/one", "main")
        self.assertIn("new.ts", result)
        self.assertNotIn("old.ts", result)

    # ------------------------------------------------- audit 2026-08-05, H3
    def test_touched_files_is_none_when_the_merge_base_cannot_be_found(self):
        """An incomplete file set silently understates collisions.

        Before this, a failed merge-base left `touched_files` returning only the
        uncommitted files, so a worktree with 40 committed changes looked like it
        had touched almost nothing -- and the collisions matrix confidently
        reported "No two worktrees are editing the same file."

        This is the condition `git:default-branch` already warns about: when
        origin/HEAD is unresolvable, `base` is a guess, and `git merge-base
        <guess> HEAD` fails on every worktree at once.
        """
        runner = ReplayRunner({
            "git merge-base main HEAD":
                {"returncode": 128, "stdout": "", "stderr": "not a valid object name"},
            "git diff --name-only -z HEAD": {"returncode": 0, "stdout": "", "stderr": ""},
            "git ls-files --others --exclude-standard -z":
                {"returncode": 0, "stdout": "", "stderr": ""},
        })
        self.assertIsNone(touched_files(runner, "/t/one", "main"))

    def test_touched_files_is_none_when_a_diff_fails(self):
        runner = ReplayRunner({
            "git merge-base main HEAD": {"returncode": 0, "stdout": "base1\n", "stderr": ""},
            "git diff --name-only -z base1 HEAD": {"returncode": 0, "stdout": "", "stderr": ""},
            "git diff --name-only -z HEAD":
                {"returncode": 128, "stdout": "", "stderr": "fatal"},
            "git ls-files --others --exclude-standard -z":
                {"returncode": 0, "stdout": "", "stderr": ""},
        })
        self.assertIsNone(touched_files(runner, "/t/one", "main"))

    def test_a_worktree_whose_files_cannot_be_read_is_named_not_silently_skipped(self):
        """A worktree left out of the matrix must be reported, not dropped.

        Otherwise the matrix shows "no collisions" while one of the two branches
        that actually collide was never compared at all -- the empty-versus-broken
        confusion, one layer below where `sources` normally reaches.
        """
        runner = ReplayRunner({
            "git merge-base main HEAD":
                {"returncode": 128, "stdout": "", "stderr": "not a valid object name"},
            "git diff --name-only -z HEAD": {"returncode": 0, "stdout": "", "stderr": ""},
            "git ls-files --others --exclude-standard -z":
                {"returncode": 0, "stdout": "", "stderr": ""},
        })
        trees = [Worktree("/t/one", "one", "one", "h1"), Worktree("/t/two", "two", "two", "h2")]
        result, undetermined = collisions(runner, trees, "main")
        self.assertEqual(result, [])
        self.assertEqual(undetermined, ["one", "two"])

    def test_paths_with_spaces_and_non_ascii(self):
        runner = ReplayRunner({
            "git merge-base main HEAD": {"returncode": 0, "stdout": "base1\n", "stderr": ""},
            "git diff --name-only -z base1 HEAD": {"returncode": 0, "stdout": "spaced name.ts\0café.ts\0", "stderr": ""},
            "git diff --name-only -z HEAD": {"returncode": 0, "stdout": "", "stderr": ""},
            "git ls-files --others --exclude-standard -z": {"returncode": 0, "stdout": "", "stderr": ""},
        })
        result = touched_files(runner, "/t/one", "main")
        self.assertEqual(result, {"spaced name.ts", "café.ts"})


if __name__ == "__main__":
    unittest.main()
