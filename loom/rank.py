"""What deserves a human, in the order a human should deal with it."""
from __future__ import annotations


def needs_you(repo: dict) -> list[dict]:
    items: list[dict] = []

    for t in repo.get("worktrees", []):
        agent = t.get("agent") or {}
        if agent.get("state") == "waiting":
            items.append({"rank": 1, "kind": "agent_waiting", "subject": t["dir"],
                          "detail": "agent is blocked on a prompt"})

    for p in repo.get("prs", []):
        if p.get("draft"):
            continue
        if p.get("checks") == "failing":
            items.append({"rank": 4, "kind": "pr_failing", "subject": f"PR #{p['number']}",
                          "detail": "checks are failing"})
        elif not p.get("review"):
            # "none" (no CI configured) counts as not failing, or this never fires.
            items.append({"rank": 2, "kind": "pr_awaiting_review",
                          "subject": f"PR #{p['number']}", "detail": "no review yet"})

    for c in repo.get("collisions", []):
        items.append({"rank": 3, "kind": "collision", "subject": c["file"],
                      "detail": " × ".join(c["branches"])})

    for t in repo.get("worktrees", []):
        agent = t.get("agent") or {}
        dirty = t.get("dirty") or {}
        total = dirty.get("staged", 0) + dirty.get("unstaged", 0) + dirty.get("untracked", 0)
        if agent.get("state") in {"stopped", "stale"} and total:
            items.append({"rank": 5, "kind": "stopped_dirty", "subject": t["dir"],
                          "detail": f"{total} uncommitted files left behind"})

    for f in repo.get("flags", []):
        items.append({"rank": 6, "kind": f["kind"], "subject": f["subject"],
                      "detail": f.get("detail", "")})

    return sorted(items, key=lambda i: (i["rank"], i["subject"]))
