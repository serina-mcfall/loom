"""What deserves a human, in the order a human should deal with it."""
from __future__ import annotations
import re


# How recently a `waiting` claim must have been refreshed to earn rank 1.
# Half an hour: long enough that a real prompt raised just before you
# stepped away still shows, short enough that a closed terminal stops
# shouting. Tunable — this is a judgement about attention, not a fact.
RANK1_MAX_AGE_SECONDS = 30 * 60

# `reviewDecision` values that mean "no human has reviewed this yet".
#
# A WHITELIST, matching derive_checks in loom/ghsrc.py, and for the same reason:
# an unrecognised value must NOT become an alert. A blacklist's unknown case
# fires rank 2 on a state GitHub invented after this was written, and a strip
# that cries wolf is a strip nobody reads.
#
# This used to be `not p.get("review")`, testing a four-valued enum for
# truthiness. `REVIEW_REQUIRED` -- the exact state rank 2 exists to catch -- is a
# truthy string, so it read as "already reviewed" and rank 2 fired only on
# `null`, meaning only on repos with NO review requirement at all. Audit
# 2026-08-05, finding H2.
#
# Deliberately EXCLUDED:
#   APPROVED           reviewed; wanting a merge is a different condition
#   CHANGES_REQUESTED  blocked on the AUTHOR, and an agent can act on it, so it
#                      fails rank 2's rationale of "only a human moves it"
#
# "" is included alongside None because ghsrc normalises empty to None, but a
# hand-written or older snapshot may carry the empty string.
AWAITING_REVIEW = {None, "", "REVIEW_REQUIRED"}

def _natural_sort_key(s: str) -> tuple:
    """Sort key that treats embedded numbers numerically, not lexicographically.

    Ensures PR #9 sorts before PR #10 (not PR #10, PR #9).
    """
    return tuple((0, int(t)) if t.isdigit() else (1, t)
                 for t in re.split(r"(\d+)", s) if t != "")


def needs_you(repo: dict) -> list[dict]:
    items: list[dict] = []

    for t in repo.get("worktrees", []):
        agent = t.get("agent") or {}
        # RANK 1 REQUIRES A FRESH CLAIM, not merely the `waiting` label.
        #
        # A `waiting` agent is blocked on a human by definition and stops
        # refreshing its timestamp, so a session that CRASHED while waiting is
        # indistinguishable from one still waiting — the state file cannot tell
        # them apart and neither can this function.
        #
        # What it can do is refuse to raise the top alert on a claim it cannot
        # date. Before this, a terminal closed at a permission prompt kept rank 1
        # lit for twelve hours, and a strip that is never empty is a strip nobody
        # reads — which would cost the one alert the whole design rests on.
        #
        # The worktree row still shows `waiting`, so nothing is hidden; only the
        # interrupt-the-human promotion is withheld.
        age = agent.get("age_seconds")
        fresh_enough = age is not None and age <= RANK1_MAX_AGE_SECONDS
        if agent.get("state") == "waiting" and fresh_enough:
            worktree_dir = t.get("dir", "<unnamed worktree>")
            items.append({"rank": 1, "kind": "agent_waiting", "subject": worktree_dir,
                          "detail": "agent is blocked on a prompt"})

    for p in repo.get("prs", []):
        # A draft is exempt from both rank 2 (awaiting review) and rank 4 (failing checks).
        # Draft PRs are work in progress; failing checks there are expected and normal,
        # and ranking them would create noise that makes the strip unreadable.
        if p.get("draft"):
            continue
        if p.get("checks") == "failing":
            pr_number = p.get("number", "?")
            items.append({"rank": 4, "kind": "pr_failing", "subject": f"PR #{pr_number}",
                          "detail": "checks are failing"})
        elif p.get("review") in AWAITING_REVIEW:
            # "none" (no CI configured) counts as not failing, or this never fires.
            pr_number = p.get("number", "?")
            items.append({"rank": 2, "kind": "pr_awaiting_review",
                          "subject": f"PR #{pr_number}", "detail": "no review yet"})

    for c in repo.get("collisions", []):
        branches = c.get("branches", [])
        # A collision requires at least two branches; one branch is not a collision.
        if len(branches) >= 2:
            collision_file = c.get("file", "<unknown file>")
            items.append({"rank": 3, "kind": "collision", "subject": collision_file,
                          "detail": " × ".join(branches)})

    for t in repo.get("worktrees", []):
        agent = t.get("agent") or {}
        if agent.get("state") not in {"stopped", "stale"}:
            continue
        worktree_dir = t.get("dir", "<unnamed worktree>")
        dirty = t.get("dirty")

        # RANK 5 IS THE ONE GUARD THAT SPEAKS UP WHEN IT CANNOT TELL.
        #
        # Everywhere else in Loom, "cannot tell" means stay silent, because a
        # false alarm cries wolf on a strip that has to stay trustworthy. Rank 5
        # is deliberately the exception: its rationale is "work at risk of being
        # lost", so a false alarm costs one glance and a false silence costs
        # someone's uncommitted work.
        #
        # `dirty` is None when `git status` could not be run (see
        # gitsrc.dirty_counts), and absent on an older or hand-written snapshot.
        # Both mean unmeasured, and both are treated the same way.
        # Audit 2026-08-05, finding H3.
        if dirty is None:
            items.append({"rank": 5, "kind": "stopped_dirty", "subject": worktree_dir,
                          "detail": "agent stopped, and git could not be asked "
                                    "whether work was left behind"})
            continue

        total = dirty.get("staged", 0) + dirty.get("unstaged", 0) + dirty.get("untracked", 0)
        if total:
            items.append({"rank": 5, "kind": "stopped_dirty", "subject": worktree_dir,
                          "detail": f"{total} uncommitted files left behind"})

    for f in repo.get("flags", []):
        flag_kind = f.get("kind", "<unknown kind>")
        flag_subject = f.get("subject", "<no subject>")
        items.append({"rank": 6, "kind": flag_kind, "subject": flag_subject,
                      "detail": f.get("detail", "")})

    return sorted(items, key=lambda i: (i["rank"], _natural_sort_key(i["subject"])))


def rank_snapshot(snapshot: dict) -> dict:
    """Attach `needs_you` to every repo in a FINISHED snapshot, and return it.

    RANKING IS A PROJECTION OVER A COMPLETED SNAPSHOT, NEVER A STEP INSIDE ITS
    ASSEMBLY. That is the whole reason this function exists rather than the
    builder doing it inline.

    It used to be inline, in `build_snapshot`. `serve` then folded cached `gh`
    data into `repo["prs"]` *after* the builder returned, so the strip had been
    ranked against a PR list the consumer would never see -- empty on a fast
    tick, by design. With 29 of every 30 ticks fast, ranks 2 and 4 were absent
    from the strip for 58 of every 60 seconds while the panel below it listed
    the very PRs they described. Audit 2026-08-05, finding H1.

    Whoever finishes a snapshot calls this last. Anything that mutates a
    snapshot after ranking it has reintroduced the same defect, so mutate first
    and rank at the boundary -- that ordering is the invariant, not a style
    preference.
    """
    for repo in snapshot.get("repos", []):
        repo["needs_you"] = needs_you(repo)
    return snapshot
