# tests/test_cli.py
import io
import json
import os
import unittest
from contextlib import redirect_stdout

from loom.collect import SCHEMA_VERSION
from loom.rank import rank_snapshot
from loom.runner import ReplayRunner
from loom_cli import (main, discover_repos, repo_roots, parse_port, build_snapshot,
                      render_text, read_allow_list, allow_list_config)


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


class TestAllowList(unittest.TestCase):
    """Which repositories the board shows. Spec: 2026-08-06-allow-list-design.md.

    `--all` showed every `.git` child of ~/Launchpad with no filter, so three completed
    challenges occupied the board and 4 subprocess spawns per tick each. An allow list
    was chosen over a deny list because it stays four lines as Launchpad accumulates
    challenges, and over activity-based filtering because recency provably cannot
    separate the two sets -- `skills` is as stale as the repos being excluded and is
    wanted; `worktrees-challenge` is fresher and is not.

    The two absence cases are the part that matters: a missing file and an empty file
    must BOTH mean every repository, never none. A config that silently empties the
    board is the empty-versus-broken confusion this project exists to refuse.
    """

    TREE = {"/base": ["loom", "serina-learning", "skills", "nextjs-project", "loosefile"],
            "/base/loom": [".git"], "/base/serina-learning": [".git"],
            "/base/skills": [".git"], "/base/nextjs-project": [".git"],
            "/base/loosefile": []}

    def _listdir(self, d):
        if d not in self.TREE:
            raise NotADirectoryError(d)
        return self.TREE[d]

    def _names(self, allow):
        return [p.rsplit("/", 1)[-1]
                for p in discover_repos("/base", self._listdir, allow=allow)]

    # ---------------------------------------------------------- the absences
    def test_no_allow_list_shows_every_repository(self):
        # Absent config must never mean an empty board.
        self.assertEqual(self._names(None),
                         ["loom", "nextjs-project", "serina-learning", "skills"])

    def test_an_empty_allow_list_shows_every_repository(self):
        # Approved explicitly: an empty file is far likelier to be a truncated write
        # than a request for a blank board.
        self.assertEqual(self._names([]),
                         ["loom", "nextjs-project", "serina-learning", "skills"])

    # ---------------------------------------------------------- the filtering
    def test_only_the_named_repositories_are_returned(self):
        self.assertEqual(self._names(["loom", "skills"]), ["loom", "skills"])

    def test_a_repository_absent_from_the_list_is_excluded(self):
        # The negative control for the test above.
        self.assertNotIn("nextjs-project", self._names(["loom", "skills"]))

    def test_a_name_that_matches_nothing_does_not_remove_the_good_ones(self):
        # A typo must not silently shrink the board to nothing.
        self.assertEqual(self._names(["loom", "serina-skils"]), ["loom"])

    def test_a_non_repository_directory_is_still_excluded_even_if_listed(self):
        # `loosefile` has no .git; naming it must not conjure a repository.
        self.assertEqual(self._names(["loom", "loosefile"]), ["loom"])


class TestConfigField(unittest.TestCase):
    """The honesty channel. Spec: a name matching no repository is REPORTED, never
    silently dropped -- the same failure as `gh` returning empty with exit code 0.

    `config` is present on EVERY snapshot, including single-repo runs, because a field
    that appears and disappears is a field consumers get wrong.
    """

    TREE = {"/base": ["loom", "skills"], "/base/loom": [".git"], "/base/skills": [".git"]}

    def _listdir(self, d):
        if d not in self.TREE:
            raise NotADirectoryError(d)
        return self.TREE[d]

    def test_a_missing_name_is_reported(self):
        cfg = allow_list_config("/p/repos", ["loom", "serina-skils"], "/base", self._listdir)
        self.assertEqual(cfg["missing"], ["serina-skils"])
        self.assertEqual(cfg["listed"], 2)
        self.assertEqual(cfg["source"], "/p/repos")

    def test_names_that_all_exist_report_nothing_missing(self):
        # The negative control: `missing` must be able to come back empty.
        cfg = allow_list_config("/p/repos", ["loom", "skills"], "/base", self._listdir)
        self.assertEqual(cfg["missing"], [])

    def test_no_file_reports_a_null_source_and_nothing_listed(self):
        cfg = allow_list_config(None, None, "/base", self._listdir)
        self.assertIsNone(cfg["source"])
        self.assertEqual(cfg["listed"], 0)
        self.assertEqual(cfg["missing"], [])

    def test_an_empty_file_still_reports_its_source(self):
        # The file EXISTS and names nothing -- distinguishable from no file at all.
        cfg = allow_list_config("/p/repos", [], "/base", self._listdir)
        self.assertEqual(cfg["source"], "/p/repos")
        self.assertEqual(cfg["listed"], 0)

    def test_render_text_says_so_when_a_name_matched_nothing(self):
        snap = {"schema": SCHEMA_VERSION, "repos": [], "needs_you": [],
                "config": {"source": "/p/repos", "listed": 2, "missing": ["serina-skils"]}}
        text = render_text(snap)
        self.assertIn("serina-skils", text)

    def test_render_text_is_silent_when_nothing_is_missing(self):
        # Negative control: it must not print a warning on a healthy config.
        snap = {"schema": SCHEMA_VERSION, "repos": [], "needs_you": [],
                "config": {"source": "/p/repos", "listed": 2, "missing": []}}
        self.assertNotIn("not found", render_text(snap).lower())


class TestReadAllowList(unittest.TestCase):
    """Parsing the file. The reader is injected so ABSENCE can be tested -- the v1
    design's rule that a hardcoded path cannot be negative-tested."""

    def _read(self, text):
        def reader(path):
            if text is None:
                raise FileNotFoundError(path)
            return text
        return read_allow_list("/nowhere/repos", reader)

    def test_a_missing_file_reads_as_none_not_an_empty_list(self):
        # None and [] both mean "show everything", but they are different FACTS and the
        # `config` field reports them differently.
        self.assertIsNone(self._read(None))

    def test_one_name_per_line(self):
        self.assertEqual(self._read("loom\nskills\n"), ["loom", "skills"])

    def test_comments_and_blank_lines_are_ignored(self):
        self.assertEqual(
            self._read("# which repos\n\nloom\n\n# done with this one\nskills\n"),
            ["loom", "skills"])

    def test_an_inline_comment_is_stripped(self):
        self.assertEqual(self._read("loom  # the dashboard itself\n"), ["loom"])

    def test_surrounding_whitespace_is_stripped(self):
        self.assertEqual(self._read("  loom\t\n\tskills  \n"), ["loom", "skills"])

    def test_a_file_of_only_comments_reads_as_an_empty_list(self):
        # Empty list, not None: the file EXISTS. `config.source` should say so.
        self.assertEqual(self._read("# nothing here yet\n\n"), [])

    def test_an_unreadable_file_reads_as_none_rather_than_raising(self):
        def reader(path):
            raise PermissionError(path)
        self.assertIsNone(read_allow_list("/nowhere/repos", reader))


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


class TestUsage(unittest.TestCase):
    """Audit 2026-08-05, finding L10.

    An explicit help request is a SUCCESSFUL invocation. Exiting 2 makes
    `loom --help` fail inside any script or Makefile that checks status, and it
    conflates "you asked for help" with "you got the arguments wrong" -- which must
    stay distinguishable, because only one of them is an error.
    """

    def _run(self, argv):
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = main(argv)
        return code, buf.getvalue()

    def test_asking_for_help_succeeds(self):
        for argv in (["--help"], ["-h"], ["help"]):
            with self.subTest(argv=argv):
                code, out = self._run(argv)
                self.assertEqual(code, 0, f"{argv} should succeed")
                self.assertIn("usage:", out)

    def test_no_arguments_at_all_is_still_an_error(self):
        # Negative control: bare `loom` is a misuse, not a help request, and must
        # keep its non-zero exit or this change would hide real mistakes.
        code, out = self._run([])
        self.assertEqual(code, 2)
        self.assertIn("usage:", out)

    def test_an_unknown_command_is_still_an_error(self):
        code, out = self._run(["frobnicate"])
        self.assertEqual(code, 2)
        self.assertIn("usage:", out)


class TestRenderText(unittest.TestCase):
    """An empty panel and a broken panel must never read the same."""

    def _snapshot(self, sources, prs):
        return {"schema": SCHEMA_VERSION, "repos": [{
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


class TestRenderTextCost(unittest.TestCase):
    """Step 7: the per-worktree token/cost rows and the fleet total line."""

    def _wt_cost(self, notional=None, unknown_reason=None, tokens=None, model=None,
                live=0, stale=0, stopped=0, undated=0):
        """A single worktree's cost dict, matching loom/cost.py's own shape."""
        return {
            "tokens": tokens, "notional_cost_usd": notional, "model": model,
            "models": [], "prices_as_of": "2026-08-27",
            "unknown_reason": unknown_reason,
            "live_sessions": live, "stale_sessions": stale,
            "stopped_sessions": stopped, "undated_sessions": undated,
        }

    def _repo(self, name, worktrees):
        return {"name": name, "worktrees": worktrees, "prs": [], "issues": [],
                "sources": [], "needs_you": []}

    def _snapshot(self, repos):
        """Builds snap["cost"] via the REAL fleet_total(), so this test
        cannot drift from that function's actual shape."""
        from loom.view import fleet_total
        snap = {"schema": SCHEMA_VERSION, "repos": repos, "needs_you": []}
        snap["cost"] = fleet_total(snap)
        return snap

    def test_a_known_cost_worktree_prints_the_four_buckets_model_and_figure(self):
        tokens = {"input": 100, "output": 200, "cache_read": 300,
                 "cache_write_5m": 10, "cache_write_1h": 20, "cache_write": 30}
        wt = {"dir": "loom", "cost": self._wt_cost(
            notional=12.5, tokens=tokens, model="claude-opus-5", live=1)}
        text = render_text(self._snapshot([self._repo("r", [wt])]))
        self.assertIn("loom", text)
        self.assertIn("input=100", text)
        # The COMBINED cache_write bucket, read off tokens["cache_write"] --
        # never 10 + 20 computed again in this layer.
        self.assertIn("cache_write=30", text)
        self.assertIn("cache_read=300", text)
        self.assertIn("output=200", text)
        self.assertIn("claude-opus-5", text)
        self.assertIn("12.50", text)

    def test_an_unknown_cost_worktree_prints_its_reason_not_silence(self):
        wt = {"dir": "quiet", "cost": self._wt_cost(unknown_reason="no-session")}
        text = render_text(self._snapshot([self._repo("r", [wt])]))
        self.assertIn("quiet", text)
        self.assertIn("no-session", text)

    def test_total_appears_exactly_once_across_two_repos(self):
        zero_tokens = {"input": 0, "output": 0, "cache_read": 0,
                      "cache_write_5m": 0, "cache_write_1h": 0, "cache_write": 0}
        wt1 = {"dir": "a", "cost": self._wt_cost(
            notional=1.0, tokens=zero_tokens, model="claude-opus-5", live=1)}
        wt2 = {"dir": "b", "cost": self._wt_cost(
            notional=2.0, tokens=zero_tokens, model="claude-opus-5", live=1)}
        text = render_text(self._snapshot(
            [self._repo("one", [wt1]), self._repo("two", [wt2])]))
        self.assertEqual(text.count("notional (list-price equivalent"), 1,
                         "the fleet total must print once per invocation, "
                         "not once per repo")
        self.assertIn("$3.00", text)  # 1.0 + 2.0, summed once

    def test_session_counts_appear_beside_the_total(self):
        tokens = {"input": 0, "output": 0, "cache_read": 0,
                 "cache_write_5m": 0, "cache_write_1h": 0, "cache_write": 0}
        wts = [
            {"dir": "live1", "cost": self._wt_cost(notional=0.0, tokens=tokens, live=1)},
            {"dir": "stale1", "cost": self._wt_cost(notional=0.0, tokens=tokens, stale=2)},
            {"dir": "stopped1", "cost": self._wt_cost(notional=0.0, tokens=tokens, stopped=3)},
            {"dir": "undated1", "cost": self._wt_cost(unknown_reason="unreadable", undated=4)},
        ]
        text = render_text(self._snapshot([self._repo("r", wts)]))
        self.assertIn("live=1", text)
        self.assertIn("stale=2", text)
        self.assertIn("stopped=3", text)
        self.assertIn("undated=4", text)

    def test_excluded_worktree_count_appears_beside_the_total(self):
        tokens = {"input": 0, "output": 0, "cache_read": 0,
                 "cache_write_5m": 0, "cache_write_1h": 0, "cache_write": 0}
        wts = [
            {"dir": "known", "cost": self._wt_cost(notional=1.0, tokens=tokens, live=1)},
            {"dir": "broken", "cost": self._wt_cost(unknown_reason="unreadable")},
            {"dir": "quiet", "cost": self._wt_cost(unknown_reason="no-session")},
        ]
        text = render_text(self._snapshot([self._repo("r", wts)]))
        # Two unknown worktrees, but only "unreadable" counts as excluded --
        # "no-session" is the normal shape of a quiet worktree (view.py's
        # own COST_EXCLUDED_REASONS), so this must read 1, never 2.
        self.assertIn("excluded: 1 worktree(s)", text)


class TestBuildSnapshot(unittest.TestCase):
    def _recordings(self) -> dict:
        """Every git command `collect()` issues for one worktree, include_gh=False.

        One fixture for the whole class. `tests/test_serve.py::_fast_tick_runner`
        holds a near-identical copy for the same scenario -- see N1 in the
        remediation log; consolidating them is deferred, not forgotten.
        """
        return {
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
            "git status --porcelain=v1 -z -uall": {"returncode": 0, "stdout": "", "stderr": ""},
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

    def test_attaches_needs_you_to_every_repo(self):
        runner = ReplayRunner(self._recordings())
        snapshot = build_snapshot(False, include_gh=False, runner=runner)
        self.assertEqual(len(snapshot["repos"]), 1)

        # CONTRACT CHANGE, audit 2026-08-05 finding H1. This test previously
        # asserted `build_snapshot` attaches `needs_you`, and it passed -- but
        # that placement was the defect: `serve` rewrites `prs` after the
        # builder returns, so a snapshot ranked here was ranked against data no
        # consumer ever sees. Ranking moved to `rank_snapshot`, applied last by
        # whoever publishes the snapshot.
        #
        # Absent, not empty: an unranked snapshot must be distinguishable from a
        # ranked one that found nothing, or "the fleet is quiet" and "nobody
        # ranked this" look identical -- the empty-versus-broken confusion this
        # whole project exists to refuse.
        self.assertNotIn("needs_you", snapshot["repos"][0],
                         "build_snapshot must not rank; rank_snapshot does, last")

        ranked = rank_snapshot(snapshot)
        self.assertIn("needs_you", ranked["repos"][0])
        self.assertIsInstance(ranked["repos"][0]["needs_you"], list)

    # ------------------------------------------------- audit 2026-08-05, H7
    def test_the_snapshot_states_when_it_was_generated(self):
        """The loom skill is instructed: "If the snapshot is older than 5 minutes,
        say so." It could not, ever.

        `collect()` computes `generated_at` and `duration_ms`, and
        `build_snapshot` discarded both when merging repos, so the CLI's JSON --
        the skill's only input -- carried no timestamp at all. The skill asserted
        a freshness it had no way to check, and an agent could confidently report
        a fleet state minutes out of date.

        `serve` re-stamps its own, so the page had one and the CLI did not: two
        consumers of a schema versioned specifically to stop them drifting.
        """
        runner = ReplayRunner(self._recordings())
        snapshot = build_snapshot(False, include_gh=False, runner=runner)
        self.assertIn("generated_at", snapshot)
        self.assertIn("duration_ms", snapshot)

    def test_generated_at_carries_a_timezone_so_ages_are_computable(self):
        # A naive timestamp is unanswerable, not assumable -- the rule
        # loom/agents.py's `_age_seconds` already enforces. A consumer comparing a
        # naive stamp against its own clock gets a zone-dependent answer, which is
        # how a stale snapshot reads fresh in one timezone and not another.
        from datetime import datetime
        runner = ReplayRunner(self._recordings())
        snapshot = build_snapshot(False, include_gh=False, runner=runner)
        parsed = datetime.fromisoformat(snapshot["generated_at"])
        self.assertIsNotNone(parsed.tzinfo,
                             "generated_at must carry an offset or its age cannot "
                             "be computed reliably")

    def test_the_cli_and_the_collector_agree_on_the_schema_version(self):
        # `build_snapshot` hardcoded `"schema": SCHEMA_VERSION` while `collect` used the constant,
        # so the two could drift apart in the one field whose entire job is to stop
        # drift. Audit 2026-08-05, part of L2.
        from loom.collect import SCHEMA_VERSION
        runner = ReplayRunner(self._recordings())
        snapshot = build_snapshot(False, include_gh=False, runner=runner)
        self.assertEqual(snapshot["schema"], SCHEMA_VERSION)

    def test_duration_ms_is_a_non_negative_integer(self):
        runner = ReplayRunner(self._recordings())
        snapshot = build_snapshot(False, include_gh=False, runner=runner)
        self.assertIsInstance(snapshot["duration_ms"], int)
        self.assertGreaterEqual(snapshot["duration_ms"], 0)


if __name__ == "__main__":
    unittest.main()
