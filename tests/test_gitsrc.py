import unittest
from loom.runner import ReplayRunner
from loom.gitsrc import list_worktrees, ahead_behind, dirty_counts, Dirty

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


if __name__ == "__main__":
    unittest.main()
