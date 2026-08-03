# tests/test_cli.py
import io
import json
import unittest
from contextlib import redirect_stdout

from loom_cli import main, discover_repos


class TestDiscoverRepos(unittest.TestCase):
    def test_finds_children_containing_a_git_entry(self):
        tree = {"/base": ["a", "b", "notarepo"]}
        isdir = lambda p: p in ("/base/a/.git", "/base/b/.git")
        self.assertEqual(discover_repos("/base", lambda d: tree[d], isdir),
                         ["/base/a", "/base/b"])

    def test_a_base_with_no_repos_returns_nothing(self):
        self.assertEqual(discover_repos("/base", lambda d: ["x"], lambda p: False), [])


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
