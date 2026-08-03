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

import inspect
import io
import json
import socket
import threading
import unittest
import unittest.mock
import urllib.error
import urllib.request
from contextlib import redirect_stdout
from http.server import ThreadingHTTPServer
from pathlib import Path

from loom.runner import ReplayRunner
from loom.serve import (
    Handler,
    apply_gh_cache,
    run_server,
    should_include_gh,
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
        # Deliberately no top-level "generated_at" — build_snapshot's real
        # aggregate shape doesn't carry one; a fixture that included it would
        # have hidden the KeyError this function used to raise against real data.
        return {
            "schema": 1,
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

    def test_a_fast_tick_splices_cached_prs_into_the_not_fetched_snapshot(self):
        cache = {"example": {
            "prs": [{"number": 1}], "issues": [],
            "gh_sources": [
                {"name": "gh:prs", "ok": True, "error": None},
                {"name": "gh:issues", "ok": True, "error": None},
            ],
            "cached_at": "T1",
        }}
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
        cache = {"example": {
            "prs": [], "issues": [],
            "gh_sources": [{"name": "gh:prs", "ok": True, "error": None},
                          {"name": "gh:issues", "ok": True, "error": None}],
            "cached_at": "T1",
        }}
        snap = self._snap(prs=[], gh_ok=False)
        apply_gh_cache(snap, cache, include_gh=False, now_iso="T2")
        names = [s["name"] for s in snap["repos"][0]["sources"]]
        self.assertEqual(names.count("git"), 1)


class TestTickSkipsGhOnFastTick(unittest.TestCase):
    """The regression guard: a fast tick must never spawn `gh`, not once."""

    def _replay_runner(self) -> ReplayRunner:
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
            "git ls-files --others --exclude-standard -z":
                {"returncode": 0, "stdout": "", "stderr": ""},
            "git log --all --no-merges -n 40 "
            "--format=%x1e%h%x1f%aI%x1f%s%x1f%D --numstat":
                {"returncode": 0, "stdout": "", "stderr": ""},
        }
        return ReplayRunner(recordings)

    def test_no_gh_command_appears_in_the_runners_captured_calls(self):
        runner = self._replay_runner()
        cache: dict = {}
        snap = _tick(all_repos=False, include_gh=False, cached_gh=cache, runner=runner)
        gh_calls = [call for call in runner.calls if call and call[0] == "gh"]
        self.assertEqual(gh_calls, [])
        # And the snapshot is honest that gh was skipped, not silently empty.
        sources = {s["name"]: s for s in snap["repos"][0]["sources"]}
        self.assertFalse(sources["gh:prs"]["ok"])

    def test_repo_roots_lookup_itself_is_a_git_command_not_a_gh_one(self):
        runner = self._replay_runner()
        _tick(all_repos=False, include_gh=False, cached_gh={}, runner=runner)
        self.assertTrue(all(call[0] == "git" or call[0] == "tmux" for call in runner.calls))


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
        prev = {"schema": 1, "repos": [{"name": "example"}],
               "collected": True, "generated_at": "T1", "refresh_error": None}
        with unittest.mock.patch("loom.serve._tick", side_effect=RuntimeError("boom")):
            snap = _refresh_step(prev, all_repos=False, include_gh=False, cached_gh={})
        # The previous, good data survives untouched — including its timestamp.
        self.assertEqual(snap["repos"], prev["repos"])
        self.assertTrue(snap["collected"])
        self.assertEqual(snap["generated_at"], "T1")

    def test_the_failures_type_and_message_are_recorded(self):
        prev = {"schema": 1, "repos": [], "collected": False}
        with unittest.mock.patch("loom.serve._tick", side_effect=RuntimeError("boom")):
            snap = _refresh_step(prev, all_repos=False, include_gh=False, cached_gh={})
        self.assertIn("RuntimeError", snap["refresh_error"])
        self.assertIn("boom", snap["refresh_error"])

    def test_a_successful_step_after_a_failure_clears_refresh_error(self):
        prev = {"schema": 1, "repos": [], "collected": False,
               "refresh_error": "RuntimeError: boom"}
        good = {"schema": 1, "repos": [{"name": "example"}]}
        with unittest.mock.patch("loom.serve._tick", return_value=good):
            snap = _refresh_step(prev, all_repos=False, include_gh=False, cached_gh={})
        self.assertIsNone(snap["refresh_error"])
        self.assertEqual(snap["repos"], [{"name": "example"}])

    def test_a_successful_step_stamps_generated_at(self):
        prev = {"schema": 1, "repos": [], "collected": False}
        good = {"schema": 1, "repos": []}
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
        self.assertEqual(_json.loads(out.stdout), {"schema": 1, "repos": [], "collected": False})

    def test_a_tick_marks_its_snapshot_collected(self):
        runner = TestTickSkipsGhOnFastTick()._replay_runner()
        snap = _tick(all_repos=False, include_gh=False, cached_gh={}, runner=runner)
        self.assertTrue(snap["collected"])

    def test_not_yet_collected_and_genuinely_empty_are_never_equal(self):
        # The whole point of the fix: these two states must be distinguishable
        # by any consumer that just compares/serializes the snapshot dict.
        not_yet = {"schema": 1, "repos": [], "collected": False}
        genuinely_empty = {"schema": 1, "repos": [], "collected": True}
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


class TestHandlerRoutes(unittest.TestCase):
    """The HTTP layer, against a real but ephemeral (port-0) socket.

    Torn down in tearDown() so nothing is left listening once the suite moves on.
    """

    def setUp(self):
        serve._snapshot = {"schema": 1, "repos": [{"name": "example"}], "collected": True}
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

    def test_snapshot_json_returns_the_current_snapshot(self):
        with self._get("/snapshot.json") as r:
            self.assertEqual(r.status, 200)
            data = json.loads(r.read())
        self.assertEqual(data["repos"][0]["name"], "example")

    def test_snapshot_json_is_503_before_the_first_collection_completes(self):
        serve._snapshot = {"schema": 1, "repos": [], "collected": False}
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
        serve._snapshot = {"schema": 1, "repos": [], "collected": True}
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
        self.assertTrue(body.startswith(b'data: {"schema": 1'), body)

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


if __name__ == "__main__":
    unittest.main()
