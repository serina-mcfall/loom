"""A small local server. Two clocks: git is cheap and fast, gh is not."""
from __future__ import annotations

import json
import threading
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .runner import Runner

STATIC = Path(__file__).resolve().parent / "static"
FAST_SECONDS = 2
SLOW_SECONDS = 60

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
    """Fold gh data across ticks: refresh the cache on a slow (gh-including) tick,
    or splice cached PRs/issues into a fast tick's snapshot so the display never
    goes blank between slow ticks.

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
        if include_gh:
            cached_gh[repo["name"]] = {
                "prs": repo["prs"], "issues": repo["issues"],
                "gh_sources": [x for x in repo["sources"] if x["name"].startswith("gh")],
                "cached_at": now_iso,
            }
        elif repo["name"] in cached_gh:
            c = cached_gh[repo["name"]]
            repo["prs"], repo["issues"] = c["prs"], c["issues"]
            repo["sources"] = [x for x in repo["sources"]
                               if not x["name"].startswith("gh")] + c["gh_sources"]
            repo["gh_cached_at"] = c["cached_at"]
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
    from loom_cli import build_snapshot
    snap = build_snapshot(all_repos, include_gh=include_gh, runner=runner)
    apply_gh_cache(snap, cached_gh, include_gh)
    snap["collected"] = True
    return snap


def _refresh_loop(all_repos: bool) -> None:
    """git and hooks every FAST_SECONDS; gh at most once every SLOW_SECONDS."""
    global _snapshot
    last_slow = 0.0
    cached_gh: dict[str, dict] = {}
    while True:
        now = time.monotonic()
        include_gh = should_include_gh(now, last_slow, bool(cached_gh))
        snap = _tick(all_repos, include_gh, cached_gh)
        if include_gh:
            last_slow = now
        with _lock:
            _snapshot = snap
        time.sleep(FAST_SECONDS)


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt: str, *args: object) -> None:  # keep the pane quiet
        pass

    def _send(self, code: int, body: bytes, ctype: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_file(self, path: Path, ctype: str) -> None:
        try:
            body = path.read_bytes()
        except OSError:
            self._send(404, b"not found", "text/plain")
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
            last = None
            try:
                while True:
                    with _lock:
                        body = json.dumps(_snapshot)
                    if body != last:
                        self.wfile.write(f"data: {body}\n\n".encode())
                        self.wfile.flush()
                        last = body
                    time.sleep(FAST_SECONDS)
            except (BrokenPipeError, ConnectionResetError):
                return
        else:
            self._send(404, b"not found", "text/plain")


def run_server(port: int = 8787, all_repos: bool = False, host: str = "127.0.0.1") -> int:
    threading.Thread(target=_refresh_loop, args=(all_repos,), daemon=True).start()
    server = ThreadingHTTPServer((host, port), Handler)
    print(f"Loom on http://{host}:{port}  (ctrl-c to stop)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")
    return 0
