# tests/test_cli.py
import io
import json
import unittest
from contextlib import redirect_stdout

from loom_cli import main, discover_repos


class TestDiscoverRepos(unittest.TestCase):
    def test_a_linked_worktree_whose_git_is_a_file_is_included(self):
        # The regression this fix round exists for: a linked worktree's .git is a
        # file, not a directory. Testing isdir(child/.git) silently skips it.
        tree = {"/base": ["linked-wt"], "/base/linked-wt": [".git", "README.md"]}
        self.assertEqual(discover_repos("/base", lambda d: tree[d]), ["/base/linked-wt"])

    def test_a_plain_clone_whose_git_is_a_directory_is_still_included(self):
        tree = {"/base": ["main-repo"], "/base/main-repo": [".git", "README.md"]}
        self.assertEqual(discover_repos("/base", lambda d: tree[d]), ["/base/main-repo"])

    def test_a_child_with_no_git_and_a_plain_file_are_both_excluded(self):
        tree = {"/base": ["notarepo", "loosefile.txt"], "/base/notarepo": ["README.md"]}

        def listdir(d):
            if d == "/base/loosefile.txt":
                raise NotADirectoryError(d)  # a file, not a directory
            return tree[d]

        self.assertEqual(discover_repos("/base", listdir), [])

    def test_a_base_with_no_repos_returns_nothing(self):
        tree = {"/base": ["x"], "/base/x": ["notes.txt"]}
        self.assertEqual(discover_repos("/base", lambda d: tree[d]), [])

    def test_only_the_injected_listdir_is_consulted_never_the_real_filesystem(self):
        calls = []
        tree = {"/base": ["repo"], "/base/repo": [".git"]}

        def listdir(d):
            calls.append(d)
            return tree[d]

        result = discover_repos("/base", listdir)
        self.assertEqual(result, ["/base/repo"])
        self.assertEqual(sorted(calls), ["/base", "/base/repo"])


class TestCli(unittest.TestCase):
    def test_unknown_command_exits_nonzero_with_usage(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = main(["nonsense"])
        self.assertEqual(code, 2)
        self.assertIn("usage", buf.getvalue().lower())

    def test_no_command_exits_nonzero(self):
        with redirect_stdout(io.StringIO()):
            self.assertEqual(main([]), 2)


if __name__ == "__main__":
    unittest.main()
