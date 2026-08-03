import unittest
from loom.runner import ReplayRunner
from loom.gitsrc import (list_worktrees, ahead_behind, dirty_counts, Dirty, recent_commits,
                          touched_files, collisions, Worktree, default_branch)

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

    def test_failure_is_zero_zero(self):
        runner = ReplayRunner({
            "git rev-list --left-right --count main...HEAD":
                {"returncode": 128, "stdout": "", "stderr": "bad revision"},
        })
        self.assertEqual(ahead_behind(runner, "/trees/a", "main"), (0, 0))


class TestDirtyCounts(unittest.TestCase):
    def test_separates_staged_unstaged_and_untracked(self):
        runner = ReplayRunner({
            "git status --porcelain=v1": {
                "returncode": 0,
                "stdout": "M  staged.py\n M unstaged.py\nMM both.py\n?? new.py\n",
                "stderr": "",
            },
        })
        self.assertEqual(dirty_counts(runner, "/trees/a"), Dirty(staged=2, unstaged=2, untracked=1))

    def test_clean_tree_is_all_zero(self):
        runner = ReplayRunner({
            "git status --porcelain=v1": {"returncode": 0, "stdout": "", "stderr": ""},
        })
        self.assertEqual(dirty_counts(runner, "/trees/a"), Dirty(0, 0, 0))


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
        result = collisions(runner, trees, "main")
        self.assertEqual([c["file"] for c in result], ["src/a.ts", "src/b.ts"])
        self.assertEqual(result[0]["branches"], ["one", "two"])

    def test_single_tree_never_collides_with_itself(self):
        runner = ReplayRunner({
            "git merge-base main HEAD": {"returncode": 0, "stdout": "base1\n", "stderr": ""},
            "git diff --name-only -z base1 HEAD": {"returncode": 0, "stdout": "src/a.ts\0", "stderr": ""},
            "git diff --name-only -z HEAD": {"returncode": 0, "stdout": "", "stderr": ""},
            "git ls-files --others --exclude-standard -z": {"returncode": 0, "stdout": "", "stderr": ""},
        })
        trees = [Worktree("/t/one", "one", "one", "h1")]
        self.assertEqual(collisions(runner, trees, "main"), [])

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
