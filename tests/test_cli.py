# tests/test_cli.py
import io
import json
import os
import unittest
from contextlib import redirect_stdout

from loom.runner import ReplayRunner
from loom_cli import main, discover_repos, repo_roots, parse_port, build_snapshot, render_text


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


class TestParsePort(unittest.TestCase):
    """--port must fail cleanly, never a raw traceback — it goes live the moment
    Task 10's `loom.serve` exists, and every other dispatch path returns an exit code."""

    def test_missing_value_raises_a_reportable_error(self):
        with self.assertRaises(ValueError):
            parse_port(["--port"])

    def test_non_integer_value_raises_a_reportable_error(self):
        with self.assertRaises(ValueError):
            parse_port(["--port", "abc"])

    def test_port_zero_is_out_of_range(self):
        with self.assertRaises(ValueError):
            parse_port(["--port", "0"])

    def test_port_70000_is_out_of_range(self):
        with self.assertRaises(ValueError):
            parse_port(["--port", "70000"])

    def test_a_valid_port_is_parsed_to_its_integer_value(self):
        self.assertEqual(parse_port(["--port", "8080"]), 8080)


class TestServeCommandPortHandling(unittest.TestCase):
    """The `serve` dispatch itself: bad --port input must exit 2, not crash, even
    though loom.serve (Task 10) does not exist yet — parsing happens before the import."""

    def test_missing_port_value_exits_2_not_a_crash(self):
        with redirect_stdout(io.StringIO()):
            self.assertEqual(main(["serve", "--port"]), 2)

    def test_non_integer_port_exits_2_not_a_crash(self):
        with redirect_stdout(io.StringIO()):
            self.assertEqual(main(["serve", "--port", "abc"]), 2)

    def test_port_zero_exits_2_not_a_crash(self):
        with redirect_stdout(io.StringIO()):
            self.assertEqual(main(["serve", "--port", "0"]), 2)

    def test_port_70000_exits_2_not_a_crash(self):
        with redirect_stdout(io.StringIO()):
            self.assertEqual(main(["serve", "--port", "70000"]), 2)


class TestRepoRoots(unittest.TestCase):
    def _runner_for(self, stdout, returncode=0):
        return ReplayRunner({
            "git rev-parse --path-format=absolute --git-common-dir":
                {"returncode": returncode, "stdout": stdout, "stderr": ""},
        })

    def test_a_worktree_or_plain_clones_common_dir_resolves_to_its_parent(self):
        runner = self._runner_for("/repo/.git\n")
        self.assertEqual(repo_roots(False, runner), ["/repo"])

    def test_a_bare_repos_common_dir_is_the_repo_root_itself(self):
        # A bare repo's common dir has no /.git component to strip off — taking
        # dirname() unconditionally would climb one level too high.
        runner = self._runner_for("/srv/bare.git\n")
        self.assertEqual(repo_roots(False, runner), ["/srv/bare.git"])

    def test_a_relative_path_is_treated_as_a_failed_lookup(self):
        # --path-format=absolute was requested but not verified; a relative value
        # must fall back to cwd rather than silently resolve dirname("") to "".
        runner = self._runner_for("relative/path/.git\n")
        self.assertEqual(repo_roots(False, runner), [os.getcwd()])

    def test_a_failed_rev_parse_falls_back_to_cwd(self):
        runner = self._runner_for("", returncode=128)
        self.assertEqual(repo_roots(False, runner), [os.getcwd()])


class TestRenderText(unittest.TestCase):
    """An empty panel and a broken panel must never read the same."""

    def _snapshot(self, sources, prs):
        return {"schema": 1, "repos": [{
            "name": "example", "worktrees": [], "prs": prs, "issues": [],
            "sources": sources, "needs_you": [],
        }]}

    def test_a_failed_source_with_an_empty_list_is_visibly_broken(self):
        text = render_text(self._snapshot(
            sources=[{"name": "gh:prs", "ok": False, "error": "HTTP 500"}], prs=[]))
        self.assertIn("unavailable", text)
        self.assertIn("gh:prs", text)

    def test_a_successful_source_with_genuinely_zero_prs_is_not_reported_as_broken(self):
        text = render_text(self._snapshot(
            sources=[{"name": "gh:prs", "ok": True, "error": None}], prs=[]))
        self.assertNotIn("unavailable", text)


class TestBuildSnapshot(unittest.TestCase):
    def test_attaches_needs_you_to_every_repo(self):
        recordings = {
            "git rev-parse --path-format=absolute --git-common-dir":
                {"returncode": 0, "stdout": "/repo/.git\n", "stderr": ""},
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
        runner = ReplayRunner(recordings)
        snapshot = build_snapshot(False, include_gh=False, runner=runner)
        self.assertEqual(len(snapshot["repos"]), 1)
        self.assertIn("needs_you", snapshot["repos"][0])
        self.assertIsInstance(snapshot["repos"][0]["needs_you"], list)


if __name__ == "__main__":
    unittest.main()
