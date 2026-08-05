"""A small local server. Two clocks: git is cheap and fast, gh is not."""
from __future__ import annotations

import json
import socket
import threading
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .runner import Runner

STATIC = Path(__file__).resolve().parent / "static"
FAST_SECONDS = 2
SLOW_SECONDS = 60
# A client that opens /events and never reads would otherwise block a request
# thread forever inside wfile.write() once the OS send buffer fills — and
# ThreadingHTTPServer spawns one thread per connection with no cap, so an idle
# client is enough to leak threads without bound. This turns that block into a
# timeout, treated the same as a disconnect.
SSE_IDLE_TIMEOUT = 30

_lock = threading.Lock()
# "collected": False marks the window before the first refresh finishes. Without
# it, {"repos": []} is ambiguous between "nothing has been collected yet" and
# "collection ran and there are genuinely no repos" — exactly the failure mode
# the whole `sources` mechanism in loom.collect exists to prevent elsewhere.
_snapshot: dict = {"schema": 1, "repos": [], "collected": False}


def should_include_gh(now: float, last_slow: float, have_cache: bool) -> bool:
    """True on the very first tick (nothing cached yet), else at most once per
    SLOW_SECONDS. Pure and time-source-agnostic so it is trivial to unit test —
    the caller supplies `now` (typically `time.monotonic()`)."""
    return (not have_cache) or (now - last_slow) >= SLOW_SECONDS


def _now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def apply_gh_cache(snap: dict, cached_gh: dict[str, dict], include_gh: bool,
                   now_iso: str | None = None) -> dict[str, dict]:
    """Fold gh data across ticks so the display never goes blank between slow ticks.

    TWO CLOCKS, TWO FACTS, HELD SEPARATELY:
      * the DATA is whatever the last SUCCESSFUL fetch returned
      * the STATUS is whatever the last ATTEMPT reported, success or failure

    Only a successful fetch may replace the data. An earlier version cached
    `repo["prs"]` on every gh-including tick without asking whether the fetch
    worked, so one transient `gh` failure -- a rate limit, an expired token, a
    network blip -- overwrote known-good PRs with the empty list `collect`
    correctly returns alongside `ok: False`. The thing called a cache was
    guaranteed not to hold a cached value exactly when it was needed. Audit
    2026-08-05, finding H4.

    Keeping the status separate is what stops the page flapping. Cache them
    together and a failed slow tick shows the banner, then the next fast tick
    splices the stale `ok: True` status back in two seconds later, and the page
    alternates between "gh unavailable" and a confident PR list indefinitely.

    A failed attempt stamps `last_good` from the surviving data's `cached_at`,
    which is what makes the spec's own error-honesty example -- "PRs unavailable
    - gh: HTTP 403, last good 4m ago" -- expressible at all.

    `now_iso` is accepted as a parameter (rather than read off the snapshot)
    because `build_snapshot`'s aggregate `{"schema": 1, "repos": [...]}` return
    value carries no top-level timestamp — only the per-root `collect()` call it
    wraps does, and that field is discarded when the repos are merged. Reading
    `snap["generated_at"]` here would `KeyError` against the real snapshot shape;
    verified by running this against `build_snapshot`'s actual output, not just
    hand-built test fixtures. Defaults to wall-clock time; tests pass a fixed
    string so assertions do not depend on real time.

    Mutates `snap["repos"]` in place and returns the (possibly updated) cache —
    extracted as its own function, with no threading or sockets involved, so the
    substitution logic can be unit tested directly instead of through a live
    server. This is the regression guard for the bug this design replaces: an
    earlier version called the collector (and therefore `gh`) unconditionally
    every tick and only overwrote the *displayed* result with a cache afterward,
    which is not caching — it is still 30 `gh` invocations a minute.
    """
    now_iso = now_iso if now_iso is not None else _now_iso()
    for repo in snap["repos"]:
        name = repo["name"]
        gh_now = [x for x in repo["sources"] if x["name"].startswith("gh")]
        non_gh = [x for x in repo["sources"] if not x["name"].startswith("gh")]
        entry = cached_gh.get(name)

        fetch_succeeded = include_gh and bool(gh_now) and all(x["ok"] for x in gh_now)

        if fetch_succeeded:
            # The only path that may replace cached DATA.
            cached_gh[name] = {"prs": repo["prs"], "issues": repo["issues"],
                               "status": gh_now, "cached_at": now_iso}
            continue

        if include_gh:
            # A real attempt that FAILED. Record the failure as the current status
            # but leave the data alone -- this is the H4 fix. Stamp `last_good` so
            # the banner can say how old the surviving data is, which is what the
            # spec's error-honesty example always described and nothing ever set.
            failed_status = [dict(x, last_good=entry["cached_at"] if entry else None)
                             for x in gh_now]
            if entry is not None:
                entry["status"] = failed_status
            else:
                # Nothing was ever fetched successfully, so there is no last-good
                # data to fall back on and none is invented.
                cached_gh[name] = {"prs": [], "issues": [],
                                   "status": failed_status, "cached_at": None}
            entry = cached_gh[name]

        if entry is None:
            # A fast tick before any slow tick ever ran. The honest "not fetched
            # this cycle" status must survive untouched.
            continue

        repo["prs"], repo["issues"] = entry["prs"], entry["issues"]
        # Status comes from the last ATTEMPT, data from the last SUCCESS. Holding
        # them apart is what stops the page flapping: without it, a failed slow
        # tick showed the banner and the next fast tick spliced the stale
        # `ok: True` statuses back in, two seconds later, forever.
        repo["sources"] = non_gh + entry["status"]
        if entry["cached_at"] is not None:
            repo["gh_cached_at"] = entry["cached_at"]
    return cached_gh


def _tick(all_repos: bool, include_gh: bool, cached_gh: dict[str, dict],
          runner: Runner | None = None) -> dict:
    """One refresh: build a snapshot with `include_gh` threaded all the way down
    into `collect`, then fold in the gh cache. `include_gh=False` means `gh` is
    never spawned for this tick — not called-and-discarded, genuinely skipped.

    `runner` defaults to None so production use gets the real `SubprocessRunner`
    (via `build_snapshot`'s own default); tests inject a `ReplayRunner` here to
    prove no `gh` command is ever issued when `include_gh=False`.

    `snap["collected"]` is set True here, on every real tick — the module-level
    default (see `_snapshot` above) starts False and is the only value ever seen
    before the first tick completes. A consumer must be able to tell "nothing
    collected yet" apart from "collection ran and found zero repos"; conflating
    them is exactly the failure mode `loom.collect`'s `sources` mechanism exists
    to prevent for `gh`, just one layer up, at the server boundary.
    """
    from loom.view import finalise
    from loom_cli import build_snapshot
    snap = build_snapshot(all_repos, include_gh=include_gh, runner=runner)
    apply_gh_cache(snap, cached_gh, include_gh)
    snap["collected"] = True
    # FINALISE AFTER THE SPLICE, NEVER BEFORE. `apply_gh_cache` has just rewritten
    # `repo["prs"]`; ranking earlier would score a PR list this snapshot does not
    # contain, which is precisely audit finding H1. `collected` is set first
    # because the badge reads it.
    return finalise(snap)


def _refresh_step(prev_snapshot: dict, all_repos: bool, include_gh: bool,
                  cached_gh: dict[str, dict], runner: Runner | None = None) -> dict:
    """One iteration of the refresh loop's body, extracted so a raising
    collector can be tested directly instead of by racing a real thread.

    On success: a fresh snapshot, stamped with `generated_at` (wall-clock time
    of THIS successful collection) and `refresh_error: None`.

    On failure (`_tick` raises anything): the **previous** snapshot, with
    `refresh_error` set to the exception's type and message, and
    `generated_at` left UNCHANGED — updating it on failure would make a stale
    snapshot's timestamp look fresh, defeating the one signal that lets a
    consumer detect staleness even if this function's own error surfacing is
    somehow bypassed. A frozen `generated_at` is detectable; a `generated_at`
    that keeps advancing while the underlying data doesn't is not.

    Never raises itself: this is what makes `_refresh_loop`'s `while True`
    unkillable by anything short of process exit — the specific bug this
    replaces was a bare `while True` with no `try` at all, where a `KeyError`
    (or any future exception) ended the daemon thread silently, after which
    `/snapshot.json` would serve `collected: true` and a frozen snapshot
    forever with no visible sign anything had gone wrong.
    """
    from loom.view import finalise
    try:
        snap = _tick(all_repos, include_gh, cached_gh, runner=runner)
        snap["generated_at"] = _now_iso()
        snap["refresh_error"] = None
        # Re-finalise once the final timestamp is in place, so the badge is
        # computed against the stamp this snapshot actually carries rather than
        # the builder's. `finalise` is idempotent, so this cannot double-count.
        return finalise(snap)
    except Exception as exc:
        stale = dict(prev_snapshot)
        stale["refresh_error"] = f"{type(exc).__name__}: {exc}"
        # The badge MUST be recomputed here. This is the H6 fix: the page used to
        # infer "live" from the mere arrival of an SSE message, and this path is
        # exactly what triggers one -- adding `refresh_error` changes the
        # serialised body, so a send fires. Without re-finalising, the frozen
        # snapshot would travel with its old, green badge still attached.
        return finalise(stale)


def _refresh_loop(all_repos: bool, stop: threading.Event | None = None) -> None:
    """git and hooks every FAST_SECONDS; gh at most once every SLOW_SECONDS.

    `stop` makes the loop finishable. It was `while True` with no exit condition on
    a daemon thread, so the only way out was process death -- which meant no clean
    shutdown, and no way to test the loop's own timing without really sleeping.
    Audit 2026-08-05, finding M11.

    The wait is `Event.wait`, not `time.sleep`, so a stop is honoured immediately
    instead of after up to FAST_SECONDS. Checked BEFORE the first pass too: a caller
    that has already asked it to stop must not get one more round of git subprocesses.
    """
    global _snapshot
    stop = stop or threading.Event()
    last_slow = 0.0
    cached_gh: dict[str, dict] = {}
    while not stop.is_set():
        now = time.monotonic()
        include_gh = should_include_gh(now, last_slow, bool(cached_gh))
        with _lock:
            prev = _snapshot
        snap = _refresh_step(prev, all_repos, include_gh, cached_gh)
        if snap.get("refresh_error") is None and include_gh:
            last_slow = now
        with _lock:
            _snapshot = snap
        stop.wait(FAST_SECONDS)


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt: str, *args: object) -> None:  # keep the pane quiet
        pass

    def _send(self, code: int, body: bytes, ctype: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        # NOTHING THIS SERVER SENDS IS EVER WORTH CACHING.
        #
        # There are no fingerprinted asset names and no build step, so an edited
        # loom.css or loom.js keeps its URL -- and a browser heuristically caching
        # it will happily serve the old file after a reload. Observed: a restyled
        # page came back looking entirely unchanged, which reads exactly like the
        # edit having failed rather than like a cache hit.
        #
        # The snapshot is live data by definition, so it must not be cached either.
        # One header covers both, and this server is loopback-only with a 2-second
        # refresh -- there is no bandwidth argument on the other side.
        self.send_header("Cache-Control", "no-store, must-revalidate")
        self.end_headers()
        self.wfile.write(body)

    def _send_file(self, path: Path, ctype: str) -> None:
        try:
            body = path.read_bytes()
        except FileNotFoundError:
            self._send(404, b"not found", "text/plain")
            return
        except OSError as exc:
            # Present but unreadable (permissions, a directory named like a
            # file, ...) is a different problem than absent — a 404 here would
            # send a maintainer looking for a file that already exists.
            self._send(500, f"could not read {path.name}: {exc}".encode(), "text/plain")
            return
        self._send(200, body, ctype)

    def do_GET(self) -> None:
        if self.path in ("/", "/index.html"):
            self._send_file(STATIC / "index.html", "text/html; charset=utf-8")
        elif self.path.startswith("/static/"):
            name = Path(self.path).name
            target = STATIC / name
            if not target.is_file():
                self._send(404, b"not found", "text/plain")
                return
            ctype = {"css": "text/css", "js": "text/javascript"}.get(
                name.rsplit(".", 1)[-1], "text/plain")
            self._send_file(target, f"{ctype}; charset=utf-8")
        elif self.path == "/snapshot.json":
            with _lock:
                snap = _snapshot
                body = json.dumps(snap).encode()
            # 503, not 200 with an empty list: a programmatic consumer (Task 12's
            # skill included) must be able to tell "not collected yet" from "zero
            # repos" without parsing the body — a status code is unmissable.
            code = 200 if snap.get("collected") else 503
            self._send(code, body, "application/json")
        elif self.path == "/events":
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            self.connection.settimeout(SSE_IDLE_TIMEOUT)
            try:
                while True:
                    with _lock:
                        body = json.dumps(_snapshot)
                    # EVERY TICK IS A FRAME, DELIBERATELY.
                    #
                    # This used to compare `body` against the previous one and send
                    # only on a difference -- an optimisation that could never fire
                    # once, because `_refresh_step` re-stamps `generated_at` with
                    # wall-clock time on every successful tick, so the body always
                    # differed. Dead code that read as live. Audit finding M10.
                    #
                    # It is not worth repairing with a timestamp-excluding digest,
                    # because the steady frame rate is what lets the page treat
                    # frames as a HEARTBEAT: silence means the server stopped
                    # collecting, and a page that suppressed identical frames could
                    # not tell that apart from "nothing changed". On loopback, at one
                    # snapshot every two seconds, there is nothing to save.
                    self.wfile.write(f"data: {body}\n\n".encode())
                    self.wfile.flush()
                    time.sleep(FAST_SECONDS)
            except (BrokenPipeError, ConnectionResetError, TimeoutError, socket.timeout):
                return
        else:
            self._send(404, b"not found", "text/plain")


def run_server(port: int = 8787, all_repos: bool = False, host: str = "127.0.0.1") -> int:
    # BIND BEFORE STARTING ANYTHING. The default port is fixed, so the most likely
    # reason it is taken is a Loom already running -- the single most probable user
    # error. That used to surface as a raw traceback, while `parse_port` went to real
    # trouble to give a clean message for a bad --port value. Audit finding M9.
    #
    # Binding first also means a failed start leaves no refresh thread behind
    # spawning git subprocesses every 2 seconds for the life of the process.
    try:
        server = ThreadingHTTPServer((host, port), Handler)
    except OSError as exc:
        print(f"cannot serve on {host}:{port} — {exc.strerror or exc}.")
        print(f"Port {port} is already in use; a Loom may already be running there.")
        print(f"Try `loom serve --port {port + 1}`, or stop the other one.")
        return 2

    stop = threading.Event()
    refresher = threading.Thread(target=_refresh_loop, args=(all_repos, stop),
                                 daemon=True)
    refresher.start()
    print(f"Loom on http://{host}:{port}  (ctrl-c to stop)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")
    finally:
        # Ask the refresh loop to finish rather than relying on process death, and
        # release the socket so an immediate restart is not refused. `finally` so
        # this holds however serve_forever ends.
        stop.set()
        server.server_close()
        refresher.join(timeout=FAST_SECONDS + 1)
    return 0
