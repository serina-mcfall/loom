Issue #15 — HEAD requests return 501, so anything health-checking the server sees it as broken
Stated size: no `Size` line → directed by Serina at planning time (2026-09-06) to treat as ≤30 minutes → cap: 5 steps

ALREADY TRUE  (verified against git and a live run, not notes)
  Handler(BaseHTTPRequestHandler) implements do_GET only (loom/serve.py:255,294)
    — confirmed by grep: no do_HEAD, do_POST, or any other do_* method exists
    anywhere in loom/serve.py
  BaseHTTPRequestHandler's default handling for an unimplemented do_* method
    is a 501 — reproduced live: started `loom serve` and ran
    `curl -sI http://127.0.0.1:8787/`, got "HTTP/1.1 501 Unsupported method
    ('HEAD')"
  do_GET routes four paths (loom/serve.py:294-334+):
    "/" or "/index.html"  -> loom/static/index.html
    "/static/<name>"      -> that static file, or 404
    "/snapshot.json"      -> the live snapshot JSON, 200 if collected else 503
    "/events"             -> an INDEFINITE Server-Sent-Events stream
  _send(code, body, ctype) is the one place the first three routes send their
    response (loom/serve.py:261-278): computes Content-Length from len(body),
    sends Cache-Control: no-store, then unconditionally writes the body via
    self.wfile.write(body)
  /events does NOT go through _send — it sends its own headers directly, then
    loops forever inside `while True:` writing SSE frames on `_lock`-protected
    `_snapshot` state until the client disconnects or SSE_IDLE_TIMEOUT (30s,
    loom/serve.py:23) elapses (loom/serve.py:315-334+)
  CORRECTION — an earlier draft of this section claimed no real-server test
    existed anywhere in this suite. FALSE, found by an independent
    review-plan pass (2026-09-06): tests/test_serve.py:626-806 already
    defines TestHandlerRoutes, a real ThreadingHTTPServer(("127.0.0.1", 0),
    Handler) started in setUp() on a daemon thread, torn down in tearDown()
    (shutdown/server_close/thread.join), with a self._get(path) helper over
    urllib.request.urlopen for ordinary GET assertions and raw-socket reads
    for /events specifically (test_events_streams_a_schema_one_frame_
    immediately, at :718-738). CORRECTED — an earlier draft of this line
    said that method "reads exactly up to the header/body boundary," the
    same technique step 2 needs; found false by a fourth independent
    review-plan pass (2026-09-06), and this was a live contradiction with
    step 3's own text, not just an inaccuracy: the real loop is
    `while b"\r\n\r\n" not in data or len(data.split(b"\r\n\r\n", 1)[1]) <
    20`, which reads the header AND at least 20 bytes of BODY — step 3
    already says so correctly and explicitly forbids reusing this combined
    loop for HEAD. This line agreed with step 3 in effect but described the
    method wrong, which is exactly the kind of thing that reads fine on its
    own and only breaks if an implementer trusts this section before
    reaching step 3's own, correct instruction. The earlier claim came from grepping this file
    and only reading the first 40 lines of that grep's output, which ended
    before line 626. This plan now EXTENDS TestHandlerRoutes rather than
    building a second, duplicate server lifecycle beside it.
  urllib.request.Request(url, method="HEAD") is the correct way to issue a
    HEAD through the SAME self._get()-style call this class already uses —
    confirmed live: req.get_method() returns "HEAD" as constructed. No new
    HTTP client mechanism is needed for the three _send-routed paths.
    /events needs the raw-socket approach, for TWO DIFFERENT reasons
    depending on the method — CORRECTED, an earlier draft's single reason
    ("urllib can't be used there at all, for GET or HEAD alike") was found
    false for HEAD by an independent review-plan pass (2026-09-06): urllib
    completes a HEAD /events request in ~20-30ms and returns identically
    whether the SSE loop is entered or not (verified live against both a
    broken build and the fixed one), because HTTP never expects a body on
    a HEAD response, so urllib's reader doesn't wait for one. That makes
    urllib exactly as UNFALSIFIABLE for HEAD as http.client was for the
    Blocker Round 1 found — it would "work" and prove nothing. For GET,
    urllib genuinely CANNOT be used at all (the existing class's own
    comment at :719-723 explains why: no Content-Length, no chunked
    encoding, by design — urllib's reader blocks waiting for a body shape
    that never completes). So: GET needs a raw socket because urllib
    cannot complete the request; HEAD needs one because urllib COULD
    complete it, deceptively, without proving anything.
  README.md documents the test count in its "Running the tests" section
    (currently 347, per the prior branch's own fix) — this plan will move it
    again once new tests land

STEP 1  loom/serve.py: do_HEAD for the three body-bearing routes            [independent]  ← RUNS HERE
        Add `_head: bool = False` as a CLASS-LEVEL ATTRIBUTE on Handler, not
        only an instance attribute set inside do_HEAD. Found by an
        independent review-plan pass on this exact plan (2026-09-06): a
        literal reading that only ever does `self._head = True` inside
        do_HEAD, with no default, raises AttributeError on the very first
        plain GET a connection ever serves (any GET that never had a
        preceding HEAD on the same instance) — reproduced live by that
        review. The class-level default is what makes GET safe by
        construction rather than by every caller remembering to check
        hasattr/getattr first.
        Add a do_HEAD(self) method. It sets self._head = True, calls
        self.do_GET(), then clears it (self._head = False) in a finally
        block — the SAME routing logic as GET runs (path matching, file
        reads, JSON serialisation), so the real Content-Length is always
        sent, never guessed or zeroed. Modify _send() to check the flag and
        skip self.wfile.write(body) when it is set — every other line in
        _send (status, Content-Type, the real Content-Length, Cache-Control)
        stays identical between GET and HEAD, which is the literal fix the
        issue itself names: "answer HEAD with the same status and headers
        as GET and no body."
        THIS COVERS "/", "/index.html", "/static/*", and "/snapshot.json" —
        every route that goes through _send. It does NOT yet cover /events,
        which never calls _send (see step 2).
        done when: a real ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        started in a background thread; a real http.client.HTTPConnection
        HEAD to "/static/loom.css" returns 200, a Content-Length header equal
        to the real file's byte length, and response.read() == b"" (an empty
        body, not a zero-length placeholder); the identical GET request
        returns the same Content-Length with a non-empty body; a HEAD to
        "/snapshot.json" before any collection has run returns 503 (matching
        do_GET's own honesty rule at serve.py:313), never 200 — proving the
        shared routing logic, not a hardcoded 200, drives the HEAD response;
        AND a plain GET to "/" sent as the FIRST request ever served by a
        freshly-started server (no prior HEAD on that connection or any
        other) succeeds with no AttributeError — the specific crash the
        independent review reproduced against an earlier draft of this step.

STEP 2  loom/serve.py: /events answers HEAD without entering the SSE loop   [needs 1]
        /events sends its headers manually and then loops forever — the
        do_HEAD-calls-do_GET approach from step 1 does NOT by itself stop
        that loop, because the loop writes frames directly to self.wfile with
        no check of the _head flag. A HEAD to /events today would hang for up
        to SSE_IDLE_TIMEOUT (30s) or forever, which is worse than the current
        501: a health-check that used to fail fast now fails slow.
        Add an explicit check right after the /events branch sends its
        headers: if self._head, return immediately (never enter the while
        True: loop, never touch _lock or _snapshot).
        done when: A RAW SOCKET, NOT http.client — found by an independent
        review-plan pass on this exact plan (2026-09-06): http.client never
        reads a body for a HEAD request regardless of what the server
        actually writes to the wire, so "the request completes quickly"
        is true whether or not the while-True loop was entered; that
        reviewer measured a genuinely-broken build (Step 1 only, loop still
        entered, real frames still written every tick) and a genuinely-fixed
        one (this step's early return) at the same ~2ms via http.client —
        indistinguishable, so that check would pass on a regressed build.
        The falsifiable version: open a raw socket, send a literal HEAD
        /events request, read and discard exactly the header block up to
        the blank line, THEN attempt one more read with a short
        socket-level timeout (e.g. 1s, well under SSE_IDLE_TIMEOUT). On the
        fixed build that read must time out / return no bytes (server
        already closed or is sending nothing further) — on a build that
        still enters the loop, that same read returns real SSE frame bytes
        within the tick interval, failing the test. The identical GET
        request to /events still streams real frames (unaffected by the new
        branch) — asserted the same way step 3 already needs to for GET:
        reading at least one frame with a socket-level timeout before
        closing the connection.

STEP 3  tests/test_serve.py: EXTEND TestHandlerRoutes, do not duplicate it  [needs 1, 2]
        ADD new test methods to the EXISTING TestHandlerRoutes class
        (:626-806) — it already owns the server lifecycle this issue needs,
        per ALREADY TRUE's correction. Do not build a second class with its
        own setUp/tearDown; that would run two real servers' worth of
        lifecycle for one feature and is exactly the mistake an earlier
        draft of this plan would have caused by claiming (wrongly) that no
        such class existed yet.
        Add a self._head(path) helper beside the existing self._get(path)
        (:644-645), built on urllib.request.Request(url, method="HEAD") —
        confirmed live this returns a request whose get_method() is "HEAD".
        New methods, following this class's own existing naming and
        assertion style: HEAD vs GET Content-Length parity on "/" and
        "/static/loom.css"; HEAD to "/snapshot.json" honouring the 200/503
        collected-or-not rule from step 1's done-when (reusing this class's
        existing pattern of setting serve._snapshot directly before the
        request, as test_snapshot_json_is_503_before_the_first_collection_
        completes already does); HEAD to "/events" per step 2's done-when.
        NOT the same read loop as test_events_streams_a_schema_one_frame_
        immediately (:718-738) — CORRECTED, an earlier draft said "same
        header-read"; found by an independent review-plan pass (2026-09-06)
        that literally reusing that method's combined loop (which only
        exits once BOTH the header AND at least 20 bytes of body have
        arrived) against a HEAD response — which never sends a body —
        blocks for the full 5s create_connection timeout and raises an
        unhandled socket.timeout, never reaching an assertion. Use TWO
        separate reads instead, exactly as step 2's own done-when
        specifies: connect the same way this class's existing method does,
        read ONLY up to the header/body blank line and stop, THEN attempt
        one further read with its own short timeout (~1s) as a SEPARATE
        step — that second read is what must time out on the fixed build
        and return real frame bytes on a broken one. The connection setup
        is shared with the existing method; the read strategy is not.
        Also: a genuinely unsupported method (e.g. DELETE) to "/" still
        returns 501, proving this change did not accidentally widen what
        the server accepts.
        done when: `python3 -m unittest tests.test_serve` passes with these
        new methods added to TestHandlerRoutes (not a new class), and
        README.md's test count comment is updated to match the new total.

PARALLEL  None of these three can run as independent subagents: step 2 edits
          the same function do_GET touches conceptually and the same file as
          step 1; step 3 needs both 1 and 2 built before its done-when can
          even be attempted. This is a strictly sequential 3-step plan.

GATES     review-code and review-tests apply to the whole diff once step 3 is
          done. review-a11y does not apply — no UI, no static/*.html/css/js
          touched. qa explore mode DOES apply: `loom serve` is a running HTTP
          interface, and probing it with a few hand-typed curl/http.client
          calls beyond the committed test suite (a HEAD to a 404 path, a HEAD
          with a query string, two rapid HEAD requests on one connection
          under HTTP/1.1 keep-alive) is exactly the kind of session explore
          mode is for.

BUDGET    Step 2/3's raw-socket /events check is the step most likely to eat
          the budget, not the setUp/tearDown lifecycle originally flagged
          here. An independent review-plan pass on this exact plan
          (2026-09-06) found the http.client-based version of this specific
          check cannot fail — it measured a genuinely broken build and a
          genuinely fixed one at indistinguishable timings. Raw-socket
          header parsing plus a short-timeout follow-up read is more fiddly
          to get right than anything else in this plan; budget for that
          specifically, not for the server lifecycle in general.

OPEN      The issue itself raises, without answering: should an unsupported
          method (POST, PUT, DELETE, ...) keep returning bare 501, or switch
          to 405 Method Not Allowed with an Allow: GET, HEAD header? This
          plan does NOT change that behaviour — recommendation, not a
          decision: 501 already reads as literally true (this server
          implements exactly GET and HEAD, full stop), where 405 implies a
          per-resource distinction ("this resource doesn't support it, try
          another") this single-purpose server doesn't have. Step 3's new
          DELETE-still-501 case exists to lock in current behaviour either
          way, not to pre-empt this decision. Serina's call before or after
          this plan builds — nothing here depends on the answer.

LEFT OUT  A CI-level `loom serve` + `curl -I` regression step, parallel to
          the existing "No server binds to 0.0.0.0" grep guard. That guard
          earned a second, independent check because it protects a security
          invariant this project treats as unrecoverable if shipped (audit
          finding, serve.py's own comments). A missing HEAD implementation is
          a Low-severity correctness bug, not that — the real-server test
          suite step 3 adds is the right level of proof for it, and a second
          CI-level copy would be redundant ceremony for an issue this small.
