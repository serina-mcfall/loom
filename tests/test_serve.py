"""Task 10: the server's two clocks.

The refresh logic is tested as pure functions — no thread, no socket, no sleep.
`TestTickSkipsGhOnFastTick` is the regression guard for the Blocker this design
replaces: an earlier version called the collector unconditionally every 2
seconds and only overwrote the *displayed* result with a cache afterward, so
`gh` was still invoked 30 times a minute. Here we call the real refresh tick
with `include_gh=False` and inspect a `ReplayRunner`'s captured calls directly.

`TestHandlerRoutes` and `TestServerBindsLoopbackOnly` exercise the HTTP layer
against a real (but ephemeral, port-0) socket, since that part cannot be
tested any other way — but they bind port 0, read back the assigned port, and
tear the server down in `tearDown`, so nothing is left listening afterward.
"""
from __future__ import annotations

import http.client
import inspect
import io
import json
import socket
import threading
import time
import unittest
import unittest.mock
import urllib.error
import urllib.request
from contextlib import redirect_stdout
from http.server import ThreadingHTTPServer
from pathlib import Path

from loom.collect import SCHEMA_VERSION
from loom.runner import ReplayRunner
from loom.serve import (
    Handler,
    apply_gh_cache,
    run_server,
    should_include_gh,
    _now_iso,
    _refresh_step,
    _tick,
)
from loom import serve


class TestShouldIncludeGh(unittest.TestCase):
    """Pure decision function: gh at most once per SLOW_SECONDS (60s)."""

    def test_the_very_first_tick_includes_gh_even_though_elapsed_time_is_zero(self):
        # now == last_slow == 0.0 would otherwise look like "just refreshed".
        self.assertTrue(should_include_gh(now=0.0, last_slow=0.0, have_cache=False))

    def test_a_tick_one_second_after_the_last_slow_tick_skips_gh(self):
        self.assertFalse(should_include_gh(now=100.0, last_slow=99.0, have_cache=True))

    def test_a_tick_exactly_sixty_seconds_later_includes_gh(self):
        self.assertTrue(should_include_gh(now=160.0, last_slow=100.0, have_cache=True))

    def test_a_tick_fifty_nine_seconds_later_still_skips_gh(self):
        self.assertFalse(should_include_gh(now=159.0, last_slow=100.0, have_cache=True))


class TestApplyGhCache(unittest.TestCase):
    """The substitution step, extracted so it never needs a live server to verify."""

    def _snap(self, prs: list, gh_ok: bool) -> dict:
        # No top-level "generated_at", and that is still deliberate -- but for a
        # DIFFERENT reason than when this was written. build_snapshot DOES carry one
        # now (finding H7). It is omitted here because `apply_gh_cache` must not read
        # it: `cached_at` records when the FETCH succeeded, not when the snapshot was
        # assembled. A fixture supplying it would let a regression that conflated the
        # two pass unnoticed.
        return {
            "schema": SCHEMA_VERSION,
            "repos": [{
                "name": "example", "prs": prs, "issues": [],
                "sources": [
                    {"name": "git", "ok": True, "error": None},
                    {"name": "gh:prs", "ok": gh_ok,
                     "error": None if gh_ok else "not fetched this cycle"},
                    {"name": "gh:issues", "ok": gh_ok,
                     "error": None if gh_ok else "not fetched this cycle"},
                ],
            }],
        }

    def test_a_slow_tick_populates_the_cache_from_the_fresh_snapshot(self):
        cache: dict = {}
        snap = self._snap(prs=[{"number": 1}], gh_ok=True)
        apply_gh_cache(snap, cache, include_gh=True, now_iso="T1")
        self.assertEqual(cache["example"]["prs"], [{"number": 1}])
        self.assertEqual(cache["example"]["cached_at"], "T1")

    def test_the_cached_at_timestamp_defaults_to_wall_clock_time_when_omitted(self):
        # Production calls this without now_iso; it must not crash and must
        # produce a real, non-empty timestamp string rather than None.
        cache: dict = {}
        snap = self._snap(prs=[], gh_ok=True)
        apply_gh_cache(snap, cache, include_gh=True)
        self.assertTrue(cache["example"]["cached_at"])

    def _good_cache(self, prs=None) -> dict:
        """A cache entry as a successful slow tick leaves it.

        `status` is the gh source list as of the last ATTEMPT, held separately
        from the data, which is as of the last SUCCESS. Keeping them apart is what
        stops the display flapping -- see the H4 tests below.
        """
        return {"example": {
            "prs": [{"number": 1}] if prs is None else prs, "issues": [],
            "status": [
                {"name": "gh:prs", "ok": True, "error": None},
                {"name": "gh:issues", "ok": True, "error": None},
            ],
            "cached_at": "T1",
        }}

    def test_a_fast_tick_splices_cached_prs_into_the_not_fetched_snapshot(self):
        cache = self._good_cache()
        snap = self._snap(prs=[], gh_ok=False)
        apply_gh_cache(snap, cache, include_gh=False, now_iso="T2")
        repo = snap["repos"][0]
        self.assertEqual(repo["prs"], [{"number": 1}])
        self.assertEqual(repo["gh_cached_at"], "T1")
        gh_sources = {s["name"]: s for s in repo["sources"] if s["name"].startswith("gh")}
        self.assertTrue(gh_sources["gh:prs"]["ok"])

    def test_a_fast_tick_with_nothing_cached_yet_leaves_the_not_fetched_status_alone(self):
        # No prior slow tick ever ran for this repo: there is nothing to splice in,
        # so the honest "not fetched this cycle" status must survive untouched.
        cache: dict = {}
        snap = self._snap(prs=[], gh_ok=False)
        apply_gh_cache(snap, cache, include_gh=False, now_iso="T1")
        repo = snap["repos"][0]
        self.assertEqual(repo["prs"], [])
        self.assertNotIn("gh_cached_at", repo)
        sources = {s["name"]: s for s in repo["sources"]}
        self.assertFalse(sources["gh:prs"]["ok"])

    def test_git_only_sources_are_never_touched_by_the_splice(self):
        cache = self._good_cache(prs=[])
        snap = self._snap(prs=[], gh_ok=False)
        apply_gh_cache(snap, cache, include_gh=False, now_iso="T2")
        names = [s["name"] for s in snap["repos"][0]["sources"]]
        self.assertEqual(names.count("git"), 1)

    # ------------------------------------------------- audit 2026-08-05, H4
    def test_a_failed_slow_tick_does_not_overwrite_a_good_cache(self):
        """THE CORE OF H4.

        `apply_gh_cache` wrote `repo["prs"]` into the cache on every gh-including
        tick without asking whether the fetch worked. When `gh` failed, `collect`
        correctly returned `prs=[]` with `ok: False` -- and that empty list
        overwrote the good cache. The mechanism named "cache" was guaranteed not
        to hold a cached value at the one moment it was needed.
        """
        cache = self._good_cache()
        failed = self._snap(prs=[], gh_ok=False)
        apply_gh_cache(failed, cache, include_gh=True, now_iso="T2")
        self.assertEqual(cache["example"]["prs"], [{"number": 1}],
                         "a failed fetch destroyed the last known good PRs")
        self.assertEqual(cache["example"]["cached_at"], "T1",
                         "cached_at must still date the last SUCCESS, not the failure")

    def test_a_failed_slow_tick_still_reports_the_failure_on_later_fast_ticks(self):
        """No flapping.

        The status of the last ATTEMPT is cached separately from the data of the
        last SUCCESS. Without that split, a failed slow tick showed the banner and
        then the very next fast tick spliced the old `ok: True` statuses back in,
        so the page alternated between "gh unavailable" and a confident PR list
        every two seconds.
        """
        cache = self._good_cache()
        apply_gh_cache(self._snap(prs=[], gh_ok=False), cache,
                       include_gh=True, now_iso="T2")

        fast = self._snap(prs=[], gh_ok=False)
        apply_gh_cache(fast, cache, include_gh=False, now_iso="T3")
        sources = {s["name"]: s for s in fast["repos"][0]["sources"]}
        self.assertFalse(sources["gh:prs"]["ok"],
                         "the failure must persist until a fetch actually succeeds")

    def test_a_failed_fetch_records_when_the_data_was_last_good(self):
        # `last_good` is declared on SourceStatus and was never once assigned
        # (audit L1), which made the spec's own error-honesty example --
        # "PRs unavailable - gh: HTTP 403, last good 4m ago" -- unimplementable.
        cache = self._good_cache()
        failed = self._snap(prs=[], gh_ok=False)
        apply_gh_cache(failed, cache, include_gh=True, now_iso="T2")
        sources = {s["name"]: s for s in failed["repos"][0]["sources"]}
        self.assertEqual(sources["gh:prs"]["last_good"], "T1")

    def test_a_successful_fetch_after_a_failure_clears_it(self):
        cache = self._good_cache()
        apply_gh_cache(self._snap(prs=[], gh_ok=False), cache,
                       include_gh=True, now_iso="T2")
        recovered = self._snap(prs=[{"number": 9}], gh_ok=True)
        apply_gh_cache(recovered, cache, include_gh=True, now_iso="T3")
        self.assertEqual(cache["example"]["prs"], [{"number": 9}])
        self.assertEqual(cache["example"]["cached_at"], "T3")
        sources = {s["name"]: s for s in recovered["repos"][0]["sources"]}
        self.assertTrue(sources["gh:prs"]["ok"])

    def test_a_failed_fetch_with_nothing_ever_cached_stays_honest(self):
        # Negative control: no prior success means there is no last-good data to
        # fall back on, and none must be invented.
        cache: dict = {}
        failed = self._snap(prs=[], gh_ok=False)
        apply_gh_cache(failed, cache, include_gh=True, now_iso="T1")
        repo = failed["repos"][0]
        self.assertEqual(repo["prs"], [])
        self.assertNotIn("gh_cached_at", repo)
        sources = {s["name"]: s for s in repo["sources"]}
        self.assertFalse(sources["gh:prs"]["ok"])
        self.assertIsNone(sources["gh:prs"].get("last_good"))


def _fast_tick_runner() -> ReplayRunner:
    """A runner recorded for one fast (gh-free) tick over a single worktree.

    Module-level rather than a method so every test that needs a fast tick shares
    ONE fixture. Two copies would be free to drift, and a fast-tick fixture that
    disagreed with itself is exactly the kind of divergence these tests exist to
    catch in production code.
    """
    # Recordings for every git command `collect()` issues with include_gh=False.
    # Deliberately contains no "gh ..." entry: if the code path ever regressed
    # to calling gh anyway, ReplayRunner would raise KeyError on the unrecorded
    # command, which is itself a second, independent failure signal.
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
            "git status --porcelain=v1 -z": {"returncode": 0, "stdout": "", "stderr": ""},
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
            "git ls-files --others --exclude-standard -z":
                {"returncode": 0, "stdout": "", "stderr": ""},
            "git log --all --no-merges -n 40 "
            "--format=%x1e%h%x1f%aI%x1f%s%x1f%D --numstat":
                {"returncode": 0, "stdout": "", "stderr": ""},
        }
    return ReplayRunner(recordings)


class TestTickSkipsGhOnFastTick(unittest.TestCase):
    """The regression guard: a fast tick must never spawn `gh`, not once."""

    def test_no_gh_command_appears_in_the_runners_captured_calls(self):
        runner = _fast_tick_runner()
        cache: dict = {}
        snap = _tick(all_repos=False, include_gh=False, cached_gh=cache, runner=runner)
        gh_calls = [call for call in runner.calls if call and call[0] == "gh"]
        self.assertEqual(gh_calls, [])
        # And the snapshot is honest that gh was skipped, not silently empty.
        sources = {s["name"]: s for s in snap["repos"][0]["sources"]}
        self.assertFalse(sources["gh:prs"]["ok"])

    def test_repo_roots_lookup_itself_is_a_git_command_not_a_gh_one(self):
        runner = _fast_tick_runner()
        _tick(all_repos=False, include_gh=False, cached_gh={}, runner=runner)
        self.assertTrue(all(call[0] == "git" or call[0] == "tmux" for call in runner.calls))


class TestNeedsYouIsRankedAfterTheGhCacheSplice(unittest.TestCase):
    """Audit 2026-08-05, finding H1.

    `build_snapshot` computed `needs_you` mid-assembly, BEFORE `apply_gh_cache`
    put the cached PRs back into `repo["prs"]`. On a fast tick `collect()`
    returns `prs=[]` by design, so every PR-derived alert -- rank 2 (awaiting
    review) and rank 4 (failing checks) -- was ranked against an empty list and
    never recomputed.

    FAST_SECONDS=2 against SLOW_SECONDS=60 makes 29 of every 30 ticks fast, so
    the triage strip the entire product rests on was empty for 58 of every 60
    seconds while the panel directly below it listed the very PRs it should
    have been ranking. The page contradicted itself on screen.

    The invariant these tests pin: whatever `repo["prs"]` a consumer is shown,
    `repo["needs_you"]` was computed from exactly that list.
    """

    def _warm_cache(self) -> dict:
        # Keyed "repo" because _fast_tick_runner's common-dir recording is
        # /repo/.git, so collect() names the repo after its root directory.
        return {"repo": {
            "prs": [
                # Rank 4: failing checks.
                {"number": 7, "branch": "b7", "draft": False,
                 "review": None, "checks": "failing"},
                # Rank 2: no review, and "none" counts as not failing.
                {"number": 8, "branch": "b8", "draft": False,
                 "review": None, "checks": "none"},
            ],
            "issues": [],
            "status": [{"name": "gh:prs", "ok": True, "error": None},
                       {"name": "gh:issues", "ok": True, "error": None}],
            "cached_at": "T1",
        }}

    def test_a_fast_tick_ranks_the_cached_prs_it_displays(self):
        snap = _tick(all_repos=False, include_gh=False,
                     cached_gh=self._warm_cache(), runner=_fast_tick_runner())
        repo = snap["repos"][0]

        # Precondition: the splice really did happen, so this test is about
        # ranking and not about an empty cache trivially producing no alerts.
        self.assertEqual([p["number"] for p in repo["prs"]], [7, 8])

        kinds = {i["kind"] for i in repo["needs_you"]}
        self.assertIn("pr_failing", kinds,
                      "PR #7's failing checks are displayed but not ranked")
        self.assertIn("pr_awaiting_review", kinds,
                      "PR #8 is displayed as unreviewed but not ranked")

    def test_the_strip_and_the_panel_never_disagree_about_which_prs_exist(self):
        """The general invariant, not just the two ranks above."""
        snap = _tick(all_repos=False, include_gh=False,
                     cached_gh=self._warm_cache(), runner=_fast_tick_runner())
        repo = snap["repos"][0]

        displayed = {f"PR #{p['number']}" for p in repo["prs"]}
        ranked = {i["subject"] for i in repo["needs_you"]
                  if i["subject"].startswith("PR #")}
        self.assertEqual(ranked, displayed,
                         "every displayed PR here warrants an alert; the strip "
                         "must not silently drop the ones the panel shows")


class TestRefreshStepSurvivesFailures(unittest.TestCase):
    """Fix round 2, FIX 1 (Blocker): a bare `while True` with no `try` died on
    the first exception anything upstream throws, after which /snapshot.json
    would serve a frozen, `collected: true` snapshot forever with no visible
    sign anything had gone wrong. `_refresh_step` must survive any exception,
    surface it, and never silently swallow the previous good data.
    """

    def _raising_tick(self, *args, **kwargs):
        raise RuntimeError("collect() exploded")

    def test_a_raising_tick_does_not_propagate_and_keeps_the_previous_snapshot(self):
        prev = {"schema": SCHEMA_VERSION, "repos": [{"name": "example"}],
               "collected": True, "generated_at": "T1", "refresh_error": None}
        with unittest.mock.patch("loom.serve._tick", side_effect=RuntimeError("boom")):
            snap = _refresh_step(prev, all_repos=False, include_gh=False, cached_gh={})
        # The previous, good data survives untouched — including its timestamp.
        self.assertEqual(snap["repos"], prev["repos"])
        self.assertTrue(snap["collected"])
        self.assertEqual(snap["generated_at"], "T1")

    def test_the_failures_type_and_message_are_recorded(self):
        prev = {"schema": SCHEMA_VERSION, "repos": [], "collected": False}
        with unittest.mock.patch("loom.serve._tick", side_effect=RuntimeError("boom")):
            snap = _refresh_step(prev, all_repos=False, include_gh=False, cached_gh={})
        self.assertIn("RuntimeError", snap["refresh_error"])
        self.assertIn("boom", snap["refresh_error"])

    def test_a_successful_step_after_a_failure_clears_refresh_error(self):
        prev = {"schema": SCHEMA_VERSION, "repos": [], "collected": False,
               "refresh_error": "RuntimeError: boom"}
        good = {"schema": SCHEMA_VERSION, "repos": [{"name": "example"}]}
        with unittest.mock.patch("loom.serve._tick", return_value=good):
            snap = _refresh_step(prev, all_repos=False, include_gh=False, cached_gh={})
        self.assertIsNone(snap["refresh_error"])
        # By name, not by whole-dict equality: `_refresh_step` now finalises, which
        # attaches `needs_you` and a badge. The assertion's intent is that the good
        # data replaced the stale data, not that the dict is byte-identical.
        self.assertEqual([r["name"] for r in snap["repos"]], ["example"])
        # The badge must stop reporting an error too. Not asserted as "live": this
        # stub `good` snapshot never sets `collected`, so "connecting" is the
        # correct reading of it, and pinning "live" here would be asserting the
        # fixture rather than the behaviour.
        self.assertNotEqual(snap["badge"]["state"], "error")

    def test_a_failed_step_travels_with_an_error_badge_not_a_green_one(self):
        """Audit 2026-08-05, finding H6, at the integration level.

        This is the path that PRODUCES an SSE message on failure: adding
        `refresh_error` changes the serialised body, so `/events` sends a frame.
        The page used to conclude "live" from the mere arrival of a frame, so the
        one moment the dashboard was lying was the moment it most confidently
        claimed to be live.

        The frozen snapshot must therefore not carry its old green badge onward.
        """
        prev = {"schema": SCHEMA_VERSION, "repos": [{"name": "example"}],
                "collected": True,
                "generated_at": _now_iso(), "refresh_error": None,
                "badge": {"state": "live", "label": "● live", "detail": ""}}
        with unittest.mock.patch("loom.serve._tick", side_effect=RuntimeError("boom")):
            snap = _refresh_step(prev, all_repos=False, include_gh=False, cached_gh={})
        self.assertEqual(snap["badge"]["state"], "error")
        self.assertIn("boom", snap["badge"]["detail"])

    def test_a_successful_step_stamps_generated_at(self):
        prev = {"schema": SCHEMA_VERSION, "repos": [], "collected": False}
        good = {"schema": SCHEMA_VERSION, "repos": []}
        with unittest.mock.patch("loom.serve._tick", return_value=good):
            snap = _refresh_step(prev, all_repos=False, include_gh=False, cached_gh={})
        self.assertTrue(snap["generated_at"])


class TestCollectedMarker(unittest.TestCase):
    """The Medium finding from the fix-round-1 review: `{"repos": []}` alone
    cannot distinguish "nothing collected yet" from "collection ran and found
    zero repos". `collected` makes the two states tell the truth about which
    one happened.
    """

    def test_the_module_level_default_snapshot_starts_uncollected(self):
        # A fresh subprocess, not this file's shared `loom.serve` module — every
        # other test class in this file mutates `serve._snapshot`, so importing
        # fresh (or reload()-ing) in-process risks reading state some earlier
        # test left behind rather than the real starting value.
        import json as _json
        import subprocess
        import sys
        out = subprocess.run(
            [sys.executable, "-c", "import json; from loom import serve; "
             "print(json.dumps(serve._snapshot))"],
            capture_output=True, text=True, timeout=10, check=True,
        )
        self.assertEqual(_json.loads(out.stdout), {"schema": SCHEMA_VERSION, "repos": [], "collected": False})

    def test_a_tick_marks_its_snapshot_collected(self):
        runner = _fast_tick_runner()
        snap = _tick(all_repos=False, include_gh=False, cached_gh={}, runner=runner)
        self.assertTrue(snap["collected"])

    def test_not_yet_collected_and_genuinely_empty_are_never_equal(self):
        # The whole point of the fix: these two states must be distinguishable
        # by any consumer that just compares/serializes the snapshot dict.
        not_yet = {"schema": SCHEMA_VERSION, "repos": [], "collected": False}
        genuinely_empty = {"schema": SCHEMA_VERSION, "repos": [], "collected": True}
        self.assertNotEqual(not_yet, genuinely_empty)
        self.assertNotEqual(json.dumps(not_yet), json.dumps(genuinely_empty))


class TestServerBindsLoopbackOnly(unittest.TestCase):
    """The single hardest constraint on this task: bind 127.0.0.1, never
    0.0.0.0 — Loom serves git history, PR data and session state, and must
    never be reachable from the network. Checked by hand once during Task 10;
    a hand check does not persist across a future edit.

    Two independent things can break the loopback guarantee, and fix-round-2's
    first pass at this class only covered one of them:

    - `run_server`'s default `host` parameter, via `inspect.signature` — fails
      the suite the moment that default changes, even if nobody ever starts a
      server in a test.
    - the actual bind CALL inside `run_server` — hardcoding `"0.0.0.0"` at the
      `ThreadingHTTPServer((host, port), Handler)` line, while leaving the
      `host="127.0.0.1"` default untouched, would satisfy the first guard and
      still listen on every interface. `test_run_server_actually_passes_the_
      loopback_host_to_the_server_constructor` calls the real `run_server` and
      inspects the tuple it actually hands to the server constructor — a
      `ThreadingHTTPServer` spy stands in so no real socket is ever opened, and
      a patched `threading.Thread` keeps the (real, subprocess-calling) refresh
      loop from ever starting. Verified by mutation: hardcoding `"0.0.0.0"` at
      that line made this test fail while leaving the other 179 tests green —
      see the fix-round-3 note in the report for the exact commands.

    An earlier version of this class also asserted `addr == "127.0.0.1"`
    immediately followed by `assertNotEqual(addr, "0.0.0.0")` against a
    hand-built `ThreadingHTTPServer(("127.0.0.1", 0), ...)` — unconditionally
    true given the line above it, since the literal was typed directly into
    the test. It tested that the socket module honors its own arguments, not
    that this codebase passes the right one. Deleted in favor of the
    mutation-verified end-to-end test above, which actually exercises
    `run_server`.
    """

    def test_run_servers_default_host_parameter_is_loopback(self):
        default = inspect.signature(run_server).parameters["host"].default
        self.assertEqual(default, "127.0.0.1")

    def test_run_server_actually_passes_the_loopback_host_to_the_server_constructor(self):
        recorded: dict = {}

        class FakeServer:
            def __init__(self, address, handler_cls):
                recorded["address"] = address

            def serve_forever(self):
                # run_server already catches KeyboardInterrupt and returns 0;
                # this ends the call without ever opening a real socket.
                raise KeyboardInterrupt

            def server_close(self):
                # run_server closes the socket in a `finally` so an immediate
                # restart is not refused (M11). A fake standing in for the real
                # server has to model the whole interface it is asked for, or the
                # test fails on the stub rather than on the behaviour.
                recorded["closed"] = True

        with unittest.mock.patch.object(serve, "ThreadingHTTPServer", FakeServer), \
             unittest.mock.patch("threading.Thread") as fake_thread_cls:
            # The refresh loop calls the real, subprocess-invoking build_snapshot;
            # patching Thread out means it is constructed (harmlessly) but
            # .start() never actually runs it.
            with redirect_stdout(io.StringIO()):
                result = serve.run_server(port=0)

        self.assertEqual(result, 0)
        fake_thread_cls.return_value.start.assert_called_once()
        self.assertEqual(recorded["address"], ("127.0.0.1", 0))
        self.assertTrue(recorded.get("closed"),
                        "the listening socket must be released on the way out")


class TestPortAlreadyInUse(unittest.TestCase):
    """Audit 2026-08-05, finding M9.

    The default port is fixed at 8787, and the most likely reason it is taken is a
    Loom already running -- so the single most probable user error produced a raw
    Python traceback. `parse_port` goes to real trouble to avoid exactly that for a
    bad `--port` value; the socket path was simply missed.
    """

    def test_a_taken_port_exits_cleanly_instead_of_raising(self):
        holder = socket.socket()
        holder.bind(("127.0.0.1", 0))
        holder.listen(1)
        port = holder.getsockname()[1]
        try:
            buf = io.StringIO()
            with redirect_stdout(buf):
                code = run_server(port=port)
            self.assertEqual(code, 2)
            out = buf.getvalue().lower()
            self.assertIn(str(port), out)
            self.assertIn("already", out)
        finally:
            holder.close()

    def test_a_failed_bind_does_not_leave_a_refresh_thread_running(self):
        # Otherwise a process that failed to start still spawns git subprocesses
        # every 2 seconds for as long as it lives.
        holder = socket.socket()
        holder.bind(("127.0.0.1", 0))
        holder.listen(1)
        port = holder.getsockname()[1]
        before = threading.active_count()
        try:
            with redirect_stdout(io.StringIO()):
                run_server(port=port)
            self.assertEqual(threading.active_count(), before,
                             "a refresh thread was started despite the bind failing")
        finally:
            holder.close()


class TestWaitSeconds(unittest.TestCase):
    """Audit 2026-08-05, part of finding M4.

    The loop slept a flat FAST_SECONDS AFTER finishing its work, so the real period
    was 2s plus collection time -- and collection is the expensive part. On a large
    fleet a "2 second" refresh silently became three or four.
    """

    def test_a_fast_tick_waits_out_the_remainder(self):
        from loom.serve import wait_seconds
        self.assertAlmostEqual(wait_seconds(0.5), serve.FAST_SECONDS - 0.5)

    def test_an_instant_tick_waits_the_whole_interval(self):
        from loom.serve import wait_seconds
        self.assertAlmostEqual(wait_seconds(0.0), serve.FAST_SECONDS)

    def test_a_tick_slower_than_the_interval_does_not_wait_negatively(self):
        # A negative wait would raise, or with Event.wait return instantly forever;
        # back-to-back ticks are the honest behaviour for a fleet that cannot keep up.
        from loom.serve import wait_seconds
        self.assertEqual(wait_seconds(serve.FAST_SECONDS + 5), 0.0)


class TestRefreshLoopIsStoppable(unittest.TestCase):
    """Audit 2026-08-05, finding M11.

    `_refresh_loop` was `while True` with no exit condition, started as a daemon
    thread, so `serve`'s only way out was process death -- and the loop's timing was
    untestable without really sleeping.
    """

    def test_an_already_set_stop_event_means_the_loop_never_runs(self):
        stop = threading.Event()
        stop.set()
        with unittest.mock.patch("loom.serve._refresh_step") as step:
            serve._refresh_loop(all_repos=False, stop=stop)
        step.assert_not_called()

    def test_the_loop_exits_when_the_event_is_set(self):
        stop = threading.Event()
        calls = []

        def one_then_stop(*a, **k):
            calls.append(1)
            stop.set()          # ask it to stop after the first pass
            return {"schema": SCHEMA_VERSION, "repos": [], "collected": True}

        with unittest.mock.patch("loom.serve._refresh_step", side_effect=one_then_stop):
            # If the loop cannot be stopped, this call never returns and the test
            # hangs -- which is itself the failure signal.
            serve._refresh_loop(all_repos=False, stop=stop)
        self.assertEqual(len(calls), 1)


class TestHandlerRoutes(unittest.TestCase):
    """The HTTP layer, against a real but ephemeral (port-0) socket.

    Torn down in tearDown() so nothing is left listening once the suite moves on.
    """

    def setUp(self):
        serve._snapshot = {"schema": SCHEMA_VERSION, "repos": [{"name": "example"}], "collected": True}
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    def _get(self, path: str):
        return urllib.request.urlopen(f"http://127.0.0.1:{self.port}{path}", timeout=2)

    def _head_request(self, path: str):
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}", method="HEAD")
        return urllib.request.urlopen(req, timeout=2)

    def test_nothing_is_cacheable(self):
        """A restyled page must not come back looking unchanged.

        There is no build step and no fingerprinted asset names, so loom.css and
        loom.js keep their URLs forever. A browser heuristically caching them
        serves the old file after a reload -- which is indistinguishable, from the
        outside, from the edit having silently failed. Observed exactly that during
        remediation, which is why this is now pinned rather than remembered.

        The snapshot is live data, so it must not be cached either; one header
        covers both, and this server is loopback-only with a 2-second refresh, so
        there is no bandwidth cost on the other side.
        """
        for path in ("/", "/static/loom.css", "/static/loom.js", "/snapshot.json"):
            with self.subTest(path=path):
                with self._get(path) as r:
                    self.assertIn("no-store", r.headers.get("Cache-Control", ""),
                                  f"{path} is cacheable")

    def test_snapshot_json_returns_the_current_snapshot(self):
        with self._get("/snapshot.json") as r:
            self.assertEqual(r.status, 200)
            data = json.loads(r.read())
        self.assertEqual(data["repos"][0]["name"], "example")

    def test_snapshot_json_is_503_before_the_first_collection_completes(self):
        serve._snapshot = {"schema": SCHEMA_VERSION, "repos": [], "collected": False}
        try:
            self._get("/snapshot.json")
            self.fail("expected an HTTPError for the not-yet-collected state")
        except urllib.error.HTTPError as exc:
            self.assertEqual(exc.code, 503)
            body = json.loads(exc.read())
        self.assertFalse(body["collected"])
        self.assertEqual(body["repos"], [])

    def test_snapshot_json_is_200_once_collected_is_true_even_with_zero_repos(self):
        # The genuinely-empty-fleet case must not also 503 — only "not yet".
        serve._snapshot = {"schema": SCHEMA_VERSION, "repos": [], "collected": True}
        with self._get("/snapshot.json") as r:
            self.assertEqual(r.status, 200)
            data = json.loads(r.read())
        self.assertEqual(data["repos"], [])
        self.assertTrue(data["collected"])

    def test_an_unknown_path_is_404_not_a_crash(self):
        with self.assertRaises(urllib.error.HTTPError) as cm:
            self._get("/nope")
        self.assertEqual(cm.exception.code, 404)

    def test_a_missing_static_file_404s_cleanly_instead_of_raising(self):
        # This used to pin the behavior by requesting "/" while the whole
        # loom/static/ directory was absent (true when Task 10 was written,
        # false the moment Task 11 landed — a test whose setup depends on a
        # file NOT existing yet has an expiry date baked in, and nothing warns
        # you when it silently starts passing for the wrong reason). A path
        # that can never exist is a condition the test controls itself instead
        # of inheriting from the repo's state.
        with self.assertRaises(urllib.error.HTTPError) as cm:
            self._get("/static/definitely-not-here.css")
        self.assertEqual(cm.exception.code, 404)

    def test_the_index_route_serves_the_real_index_html(self):
        # Task 11 built loom/static/index.html; "/" is a live route now, not
        # just a clean-404 placeholder, and nothing else in this suite covers it.
        with self._get("/") as r:
            self.assertEqual(r.status, 200)
            self.assertIn("text/html", r.headers.get("Content-Type", ""))
            body = r.read().decode()
        self.assertIn("<html", body.lower())

    def test_events_streams_a_schema_one_frame_immediately(self):
        # Not urllib: the /events response is HTTP/1.1 with neither Content-Length
        # nor chunked Transfer-Encoding (by design — it is an open-ended stream),
        # and http.client's reader blocks on that shape waiting for more than we
        # ever send. A raw socket read, the same way `curl -N` receives it, is
        # both simpler and matches the real manual verification step.
        sock = socket.create_connection(("127.0.0.1", self.port), timeout=5)
        try:
            sock.sendall(b"GET /events HTTP/1.1\r\nHost: 127.0.0.1\r\n\r\n")
            data = b""
            while b"\r\n\r\n" not in data or len(data.split(b"\r\n\r\n", 1)[1]) < 20:
                chunk = sock.recv(4096)
                if not chunk:
                    break
                data += chunk
        finally:
            sock.close()
        headers, _, body = data.partition(b"\r\n\r\n")
        self.assertIn(b"text/event-stream", headers)
        self.assertTrue(
            body.startswith(f'data: {{"schema": {SCHEMA_VERSION}'.encode()), body)

    def test_events_keeps_sending_frames_when_the_snapshot_has_not_changed(self):
        """Audit 2026-08-05, finding M10.

        `/events` compared each serialised body to the previous one and only sent on
        a difference -- an optimisation that could never once fire, because
        `_refresh_step` re-stamps `generated_at` with wall-clock time on every
        successful tick, so the body always differed. Dead code that read as live.

        The comparison is gone, and every tick is now deliberately a frame. That is
        also what lets the page treat frames as a heartbeat: silence means the server
        stopped collecting, which is the hole a suppressed-frame design would open.

        FAST_SECONDS is patched down so this costs milliseconds rather than seconds.
        """
        with unittest.mock.patch.object(serve, "FAST_SECONDS", 0.02):
            sock = socket.create_connection(("127.0.0.1", self.port), timeout=5)
            try:
                sock.sendall(b"GET /events HTTP/1.1\r\nHost: 127.0.0.1\r\n\r\n")
                data = b""
                deadline = time.monotonic() + 3
                # The snapshot is never touched during this loop, so any frame after
                # the first proves suppression is not happening.
                while data.count(b"data: ") < 3 and time.monotonic() < deadline:
                    chunk = sock.recv(4096)
                    if not chunk:
                        break
                    data += chunk
            finally:
                sock.close()
        self.assertGreaterEqual(data.count(b"data: "), 3,
                                "an unchanged snapshot stopped producing frames")

    def test_events_sets_an_idle_socket_timeout_so_an_unread_stream_cannot_hang_forever(self):
        # Fix round 2, FIX 3: a client that opens /events and never reads would
        # otherwise block the handler thread inside wfile.write() forever once
        # the OS send buffer fills, and ThreadingHTTPServer has no connection
        # cap. Forcing an actual blocked write deterministically in a unit test
        # is exactly the "thread plus socket plus sleep" flakiness this design
        # avoids elsewhere, so this checks the mechanism is wired instead:
        # settimeout() is really called, on the real accepted connection
        # socket, with the real SSE_IDLE_TIMEOUT value — a client-side
        # create_connection(timeout=...) call would also invoke settimeout,
        # so this asserts the value appears among the calls, not just that
        # settimeout was called at all.
        calls: list = []
        real_settimeout = socket.socket.settimeout

        def spy(sock_self, value):
            calls.append(value)
            return real_settimeout(sock_self, value)

        with unittest.mock.patch.object(socket.socket, "settimeout", spy):
            sock = socket.create_connection(("127.0.0.1", self.port), timeout=5)
            try:
                sock.sendall(b"GET /events HTTP/1.1\r\nHost: 127.0.0.1\r\n\r\n")
                data = b""
                # Read through the first full frame — settimeout() is called
                # before the send loop starts, so seeing a frame proves it
                # already ran on the server's side of this connection.
                while b"\r\n\r\n" not in data or len(data.split(b"\r\n\r\n", 1)[1]) < 20:
                    chunk = sock.recv(4096)
                    if not chunk:
                        break
                    data += chunk
            finally:
                sock.close()
        self.assertIn(serve.SSE_IDLE_TIMEOUT, calls)

    def test_head_matches_get_content_length_with_an_empty_body(self):
        # Issue #15: a HEAD must carry the same status and headers as the
        # equivalent GET, with no body -- proven here for both a static file
        # and the index route, the two routes _send serves directly.
        for path in ("/", "/static/loom.css"):
            with self.subTest(path=path):
                with self._get(path) as get_resp:
                    get_length = get_resp.headers.get("Content-Length")
                    get_body = get_resp.read()
                with self._head_request(path) as head_resp:
                    self.assertEqual(head_resp.status, 200)
                    self.assertEqual(head_resp.headers.get("Content-Length"), get_length)
                    head_body = head_resp.read()
                self.assertEqual(head_body, b"")
                self.assertTrue(get_body, "GET body should be non-empty for parity to mean anything")

    def test_head_snapshot_json_honours_the_503_before_collection_rule(self):
        # Same 200/503 rule do_GET already applies at serve.py:313 -- a HEAD
        # must not hardcode 200 regardless of collection state.
        serve._snapshot = {"schema": SCHEMA_VERSION, "repos": [], "collected": False}
        try:
            self._head_request("/snapshot.json")
            self.fail("expected an HTTPError for the not-yet-collected state")
        except urllib.error.HTTPError as exc:
            self.assertEqual(exc.code, 503)
            self.assertEqual(exc.read(), b"")

        serve._snapshot = {"schema": SCHEMA_VERSION, "repos": [{"name": "example"}], "collected": True}
        with self._head_request("/snapshot.json") as r:
            self.assertEqual(r.status, 200)
            self.assertEqual(r.read(), b"")

    def test_head_events_returns_without_entering_the_sse_loop(self):
        # Not urllib and not http.client for this one -- both are unfalsifiable
        # here: neither ever waits for a body on a HEAD response, so "the
        # request completed quickly" is true whether or not the server's own
        # `while True` frame loop was entered. A raw socket, reading the
        # header block and THEN attempting a separate short-timeout read, is
        # the only construction that can actually fail against a build that
        # still enters the loop (see serve.py's /events branch).
        sock = socket.create_connection(("127.0.0.1", self.port), timeout=5)
        try:
            sock.sendall(b"HEAD /events HTTP/1.1\r\nHost: 127.0.0.1\r\n\r\n")
            data = b""
            while b"\r\n\r\n" not in data:
                chunk = sock.recv(4096)
                if not chunk:
                    break
                data += chunk
            # `rest`, not `_` -- the outer loop above stops as soon as the
            # header terminator is seen, but a single recv() can return
            # bytes PAST that terminator in the same chunk. Discarding them
            # into `_` would let real frame bytes that arrived early slip
            # past this check unexamined; the assertion below must see
            # everything that followed the headers, from both this read and
            # the separate one after it.
            headers, _, rest = data.partition(b"\r\n\r\n")
            self.assertIn(b"200", headers.split(b"\r\n", 1)[0])
            self.assertIn(b"text/event-stream", headers)

            # A SEPARATE read, with its own short timeout, well under
            # SSE_IDLE_TIMEOUT -- this is what must time out on the fixed
            # build and would return real frame bytes on a regressed one.
            sock.settimeout(1)
            try:
                follow_up = sock.recv(4096)
            except (socket.timeout, TimeoutError):
                follow_up = b""
        finally:
            sock.close()
        self.assertEqual(rest + follow_up, b"",
                          "HEAD /events must not enter the SSE loop or send any frame bytes")

    def test_head_then_get_reuses_the_connection_with_a_real_body(self):
        """Guards do_HEAD's `finally: self._head = False`. If that reset
        were ever dropped (or only set inside the try, where an early
        exception could skip it), a GET immediately following a HEAD on the
        SAME kept-alive connection would silently come back with an empty
        body forever after -- indistinguishable from a passing test unless
        something actually reuses the connection and checks the body is
        real, which no other test here does.
        """
        sock = socket.create_connection(("127.0.0.1", self.port), timeout=5)
        try:
            sock.sendall(b"HEAD /static/loom.css HTTP/1.1\r\nHost: 127.0.0.1\r\n\r\n")
            data = b""
            while b"\r\n\r\n" not in data:
                chunk = sock.recv(4096)
                if not chunk:
                    break
                data += chunk
            head_headers, _, rest = data.partition(b"\r\n\r\n")
            self.assertIn(b"200", head_headers.split(b"\r\n", 1)[0])
            self.assertEqual(rest, b"", "HEAD must not carry a body into the next read")

            # Same socket, no reconnect -- proves the server considers the
            # connection still good and this handler instance's state (the
            # thing do_HEAD's finally protects) is clean for the next request.
            sock.sendall(b"GET /static/loom.css HTTP/1.1\r\nHost: 127.0.0.1\r\n\r\n")
            data = b""
            while b"\r\n\r\n" not in data:
                chunk = sock.recv(4096)
                if not chunk:
                    break
                data += chunk
            get_headers, _, get_body_so_far = data.partition(b"\r\n\r\n")
            content_length = int(
                get_headers.split(b"Content-Length: ", 1)[1].split(b"\r\n", 1)[0]
            )
            body = get_body_so_far
            while len(body) < content_length:
                chunk = sock.recv(4096)
                if not chunk:
                    break
                body += chunk
        finally:
            sock.close()
        self.assertEqual(len(body), content_length)
        self.assertGreater(len(body), 0,
                            "GET after HEAD on a reused connection came back empty")

    def test_delete_currently_returns_501_pending_the_405_decision(self):
        # This change adds do_HEAD; it must not widen what the server accepts
        # beyond GET and HEAD. A genuinely unsupported method still 501s --
        # a SNAPSHOT of current behaviour, not a lock-in of 501 over 405.
        # The plan's OPEN section reserves whether DELETE (and other verbs)
        # should someday become 405 + Allow: GET, HEAD instead; this test
        # exists so that decision has a known starting point, not so it is
        # pre-empted. Rename this alongside that decision, don't let it read
        # as "must stay 501 forever".
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        try:
            conn.request("DELETE", "/")
            resp = conn.getresponse()
            resp.read()
            self.assertEqual(resp.status, 501)
        finally:
            conn.close()


if __name__ == "__main__":
    unittest.main()
