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

    if snap.get("refresh_error"):
        return {"state": "error", "label": _LABEL["error"],
                "detail": f"collection is failing: {snap['refresh_error']}"}

    if not snap.get("collected"):
        return {"state": "connecting", "label": _LABEL["connecting"],
                "detail": "waiting for the first collection"}

    age = _age_seconds(snap.get("generated_at"), now)
    if age is None:
        # Missing, naive, unparseable or future. Cannot tell how old it is, so it
        # does not get to claim freshness.
        return {"state": "stale", "label": _LABEL["stale"],
                "detail": "cannot tell how old this data is"}
    if age > STALE_AFTER_SECONDS:
        return {"state": "stale", "label": _LABEL["stale"],
                "detail": f"last collected {int(age)}s ago"}
    return {"state": "live", "label": _LABEL["live"],
            "detail": f"collected {int(age)}s ago"}


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
    snap["badge"] = badge(snap, now)
    return snap
