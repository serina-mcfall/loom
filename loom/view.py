"""Decisions about what to display, as pure functions the tests can reach.

WHY THIS MODULE EXISTS

`loom/static/loom.js` held every display decision, and had no test of any kind --
148 lines in which two confirmed defects lived. The page cannot be reached from
the Python suite, so the remedy is to move the DECISIONS here, serialise them into
the snapshot, and leave the page rendering what it is handed. Audit 2026-08-05,
findings H6 and H8.

The split is deliberate and worth keeping:

    what to display   -> here, pure, tested   (is this data stale? which repos?)
    how to display it -> loom.js, untested    (setting textContent and classes)

Anything that decides, belongs here. Anything that only paints, belongs there. A
decision that creeps back into the page is a defect nothing can see.
"""
from __future__ import annotations

from datetime import datetime

from .collect import SCHEMA_VERSION
from .rank import rank_snapshot

# How old a snapshot may be before the page stops calling it live.
#
# serve refreshes every FAST_SECONDS (2s), so ten seconds is five missed ticks --
# long enough that a slow collection on a big fleet does not flicker the badge,
# short enough that a wedged refresh loop is visible within a glance. Not imported
# from loom.serve: this module must stay importable by the CLI, which has no
# business loading the server.
STALE_AFTER_SECONDS = 10

_LABEL = {
    # Glyph AND word, always. Colour is never the only carrier of meaning, and
    # these live here rather than in a JS lookup table so the rule is assertable.
    "connecting": "● connecting",
    "live": "● live",
    "stale": "⚠ stale",
    "error": "✕ not collecting",
    "incompatible": "✕ wrong schema",
}


def _age_seconds(stamp: str | None, now: datetime) -> float | None:
    """Seconds since `stamp`, or None when that cannot be determined.

    None means CANNOT TELL and must never be read as zero -- the same rule
    loom/agents.py's `_age_seconds` established for hook records, for the same
    reasons: a naive stamp gives a zone-dependent answer, and a future stamp is
    evidence of a broken producer rather than of health.
    """
    if not stamp:
        return None
    try:
        when = datetime.fromisoformat(stamp)
    except (TypeError, ValueError):
        return None
    if when.tzinfo is None:
        return None
    age = (now - when).total_seconds()
    return None if age < 0 else age


def badge(snap: dict, now: datetime | None = None) -> dict:
    """Whether the data on screen can be trusted, as {state, label, detail}.

    THIS IS ABOUT DATA HEALTH, NOT CONNECTION HEALTH -- the distinction H6 turned
    on. The page used to set a green "live" badge on every SSE message, and a
    message arrives *because* collection failed: `_refresh_step` returns the
    previous snapshot with `refresh_error` set, which changes the serialised body,
    which triggers a send. The one moment the dashboard was lying was the moment
    it most confidently claimed to be live.

    Precedence: error, then unknown-or-stale age, then live. `refresh_error` wins
    outright because it is the only signal that says the data is not merely old
    but actively not being collected.
    """
    now = now or datetime.now().astimezone()

    def out(state: str, detail: str) -> dict:
        # `stale_after_seconds` travels with the badge so the page can apply the SAME
        # threshold to detect silence -- frames are a heartbeat now that /events no
        # longer suppresses them (M10), and a hardcoded number in loom.js would be a
        # second copy of a policy that lives here.
        return {"state": state, "label": _LABEL[state], "detail": detail,
                "stale_after_seconds": STALE_AFTER_SECONDS}

    # SCHEMA FIRST, ABOVE EVERYTHING INCLUDING A REFRESH ERROR.
    #
    # The snapshot is versioned and the spec's stated reason is that "two consumers
    # parse it and would otherwise drift silently" -- yet neither consumer ever read
    # the number. A version field nothing validates is decoration: it records a
    # promise nothing enforces, which is this project's own definition of a boundary
    # that is not a boundary. Audit 2026-08-05, part of L2.
    #
    # It outranks the refresh error because if the shape cannot be trusted, no field
    # read out of it can be either -- including `refresh_error` itself.
    got = snap.get("schema")
    if got != SCHEMA_VERSION:
        return out("incompatible",
                   f"snapshot schema is {got!r}, this page understands "
                   f"{SCHEMA_VERSION} — refusing to read it")

    if snap.get("refresh_error"):
        return out("error", f"collection is failing: {snap['refresh_error']}")

    if not snap.get("collected"):
        return out("connecting", "waiting for the first collection")

    age = _age_seconds(snap.get("generated_at"), now)
    if age is None:
        # Missing, naive, unparseable or future. Cannot tell how old it is, so it
        # does not get to claim freshness.
        return out("stale", "cannot tell how old this data is")
    if age > STALE_AFTER_SECONDS:
        return out("stale", f"last collected {int(age)}s ago")
    return out("live", f"collected {int(age)}s ago")


def aggregate_needs(snap: dict) -> list[dict]:
    """Every repo's ranked items as ONE list, each carrying a display label.

    ONE STRIP FOR THE WHOLE FLEET, not one per repo. N polite live regions
    announcing independently is how a screen reader becomes unusable -- the same
    reasoning that debounced the strip to 15 seconds rather than letting a
    2-second region fire freely.

    The label is decided here, not in the page: with one repo the subject alone is
    unambiguous, and with several it needs the repo name or the strip both reads as
    ambiguous and looks duplicated (two repos each with a "PR #7"). That is a
    decision, so it is testable, per finding H8.

    Ordered by rank first and repo second: rank must beat repo name, or the strip
    stops being a triage order. Audit 2026-08-05, finding H5.
    """
    repos = snap.get("repos", [])
    many = len(repos) > 1
    items: list[dict] = []
    for repo in repos:
        name = repo.get("name", "<unnamed repo>")
        for item in repo.get("needs_you", []):
            subject = item.get("subject", "")
            items.append({**item, "repo": name, "show_repo": many,
                          "label": f"{name} · {subject}" if many else subject})
    return sorted(items, key=lambda i: (i["rank"], i["repo"], i.get("subject", "")))


def announcement(snap: dict) -> str:
    """What a screen reader should hear about the strip, in one short sentence.

    WHY THIS IS NOT JUST "READ THE LIST OUT". The strip re-renders every 2 seconds,
    and a live region that fires that often makes a screen reader unusable -- the
    spec says so explicitly. So the visible list is NOT a live region at all: it
    updates for the eye, and a separate permanently-polite hidden region receives
    this sentence at most every 15 seconds.

    That replaces flipping `aria-live` between "off" and "polite" on every render,
    which was the previous debounce. Readers register live regions when they enter
    the accessibility tree and do not uniformly re-read a changed `aria-live`, so the
    old mechanism could silence the region permanently for some and not at all for
    others. Right intent, fragile mechanism. Audit 2026-08-05, finding M8.

    The count sizes the problem and the top-ranked item says where to start. The rest
    stays in the visible list rather than being read aloud every 15 seconds.
    """
    items = snap.get("needs_you") or []
    if not items:
        return "Nothing needs you."
    n = len(items)
    top = items[0]
    subject = top.get("label") or top.get("subject") or "something"
    verb = "needs" if n == 1 else "need"
    noun = "item" if n == 1 else "items"
    return (f"{n} {noun} {verb} your attention. "
            f"Top: {subject}, {top.get('detail', '')}".rstrip().rstrip(",") + ".")


# unknown_reason values that mean something actually broke, for the purpose
# of the fleet total's excluded count. "no-session" is the normal state of
# most worktrees most of the time -- counting it would put a permanent
# "18 worktrees excluded" on the label and drown the signal the count exists
# to give. "no-usage-records" is excluded from the excluded-count for the
# same reason: a session that has started but not yet produced a priced
# turn is the normal shape of an agent that just began, not a measurement
# failure.
COST_EXCLUDED_REASONS = {"transcript-missing", "unreadable",
                         "missing-bucket", "unknown-model"}

_SESSION_COUNT_KEYS = ("live_sessions", "stale_sessions",
                      "stopped_sessions", "undated_sessions")


def fleet_total(snap: dict) -> dict:
    """The fleet-wide notional cost, and the four session counts step 4
    computed per worktree, summed here -- the one place that owns turning
    per-worktree numbers into a fleet-level answer, the same role
    aggregate_needs and badge already play for their own fields.

    Sums notional_cost_usd across every worktree with a KNOWN cost, and
    reports the unknown ones by count in the label text itself (OPEN-2),
    never folding an unknown into the sum as zero. Only unknown_reason in
    COST_EXCLUDED_REASONS counts as excluded -- "no-session" and
    "no-usage-records" are the normal shape of a quiet or just-started
    worktree, not a measurement failure.

    ZERO WORKTREES IS CANNOT-MEASURE, NOT MEASURED-AND-ZERO: a persistently
    failing collector and a genuinely empty fleet both hand this zero
    worktrees (`snap["repos"]` starts `[]` before the first successful
    collection, and a collection failure re-finalises the previous
    snapshot), so notional_cost_usd is None with every count at 0 -- a
    confident $0.00 can only ever mean a fleet that was actually measured
    and actually spent nothing.
    """
    worktrees = [w for repo in snap.get("repos", []) for w in repo.get("worktrees", [])]

    counts = {k: 0 for k in _SESSION_COUNT_KEYS}
    excluded = 0
    total = 0.0
    prices_as_of = None

    for w in worktrees:
        c = w.get("cost") or {}
        for key in _SESSION_COUNT_KEYS:
            counts[key] += c.get(key) or 0
        if prices_as_of is None:
            prices_as_of = c.get("prices_as_of")
        notional = c.get("notional_cost_usd")
        if notional is not None:
            total += notional
        elif c.get("unknown_reason") in COST_EXCLUDED_REASONS:
            excluded += 1

    if not worktrees:
        notional_cost_usd = None
        label = "token cost not yet measured"
    else:
        notional_cost_usd = total
        parts = [f"${notional_cost_usd:.2f} notional "
                f"(list-price equivalent, not a bill)"]
        if excluded:
            plural = "" if excluded == 1 else "s"
            parts.append(f"{excluded} worktree{plural} excluded")
        # BOTH stale and stopped fold into the same "history, not current
        # burn" clause whenever EITHER is non-zero -- OPEN-5 named stale
        # sessions only, before a stopped session's spend became populated
        # rather than unknown; reap() keeps a stopped record for 24h, so a
        # worktree's total can be dominated by a session that died 23 hours
        # ago, and that must not read as current burn either.
        if counts["stale_sessions"] or counts["stopped_sessions"]:
            parts.append(f"{counts['stale_sessions']} stale, "
                        f"{counts['stopped_sessions']} stopped session(s) "
                        f"— history, not current burn")
        if prices_as_of:
            parts.append(f"prices as of {prices_as_of}")
        label = "; ".join(parts)

    return {
        "notional_cost_usd": notional_cost_usd,
        "excluded_count": excluded,
        "prices_as_of": prices_as_of,
        "label": label,
        **counts,
    }


def finalise(snap: dict, now: datetime | None = None) -> dict:
    """Rank the snapshot and attach its display decisions. Mutates and returns it.

    THE SINGLE BOUNDARY BOTH CONSUMERS CALL. The CLI and the server each used to
    finish a snapshot their own way, which is precisely how the CLI ended up with
    no `generated_at` while the page had one (finding H7). One function, called
    last by whoever publishes, is what keeps the two shapes identical.

    Idempotent: calling it twice recomputes rather than accumulates, so a careless
    double call cannot double-count anything.
    """
    rank_snapshot(snap)
    # Top-level `needs_you` is the fleet-wide strip; each repo keeps its own list
    # because each repo panel still shows it. Same key at two levels, two scopes.
    snap["needs_you"] = aggregate_needs(snap)
    snap["announcement"] = announcement(snap)
    snap["badge"] = badge(snap, now)
    # #11 scopes the fleet total to --all, but this runs on every finalise()
    # call, including a single-repo `loom snapshot` (loom_cli.py) -- the
    # label above describes what it covers rather than claiming "fleet" over
    # one repo, so it stays honest either way.
    snap["cost"] = fleet_total(snap)
    return snap
