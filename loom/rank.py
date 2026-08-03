"""What deserves a human, in the order a human should deal with it."""
from __future__ import annotations
import re


# How recently a `waiting` claim must have been refreshed to earn rank 1.
# Half an hour: long enough that a real prompt raised just before you
# stepped away still shows, short enough that a closed terminal stops
# shouting. Tunable — this is a judgement about attention, not a fact.
RANK1_MAX_AGE_SECONDS = 30 * 60

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
        elif not p.get("review"):
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
        dirty = t.get("dirty") or {}
        total = dirty.get("staged", 0) + dirty.get("unstaged", 0) + dirty.get("untracked", 0)
        if agent.get("state") in {"stopped", "stale"} and total:
            worktree_dir = t.get("dir", "<unnamed worktree>")
            items.append({"rank": 5, "kind": "stopped_dirty", "subject": worktree_dir,
                          "detail": f"{total} uncommitted files left behind"})

    for f in repo.get("flags", []):
        flag_kind = f.get("kind", "<unknown kind>")
        flag_subject = f.get("subject", "<no subject>")
        items.append({"rank": 6, "kind": flag_kind, "subject": flag_subject,
                      "detail": f.get("detail", "")})

    return sorted(items, key=lambda i: (i["rank"], _natural_sort_key(i["subject"])))
