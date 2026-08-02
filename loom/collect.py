# loom/collect.py
"""One snapshot, assembled from every source, honest about which ones answered."""
from __future__ import annotations

import json
import os
import time
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from . import agents as agents_mod
from . import ghsrc, gitsrc
from .runner import Runner

SCHEMA_VERSION = 1


def _now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def find_flags(trees: list[gitsrc.Worktree], prs: list[ghsrc.PullRequest],
               worktree_parent: str | None,
               listdir: Callable[[str], list[str]] = os.listdir) -> list[dict]:
    flags: list[dict] = []
    branches = {t.branch for t in trees if t.branch}

    for p in prs:
        if p.branch not in branches:
            flags.append({"kind": "orphan_pr", "severity": "warn",
                          "subject": f"PR #{p.number}",
                          "detail": f"branch {p.branch} has no worktree"})

    if worktree_parent:
        known = {t.dir for t in trees}
        try:
            entries = listdir(worktree_parent)
        except OSError:
            entries = []
        for name in sorted(entries):
            if name.startswith(".") or name in known:
                continue
            flags.append({"kind": "stale_dir", "severity": "warn", "subject": name,
                          "detail": f"{name} is not a git worktree"})
    return flags


def _worktree_parent(trees: list[gitsrc.Worktree], root: str) -> str | None:
    parents = {os.path.dirname(t.path.rstrip("/")) for t in trees
               if os.path.dirname(t.path.rstrip("/")) != os.path.dirname(root.rstrip("/"))}
    return sorted(parents)[0] if len(parents) == 1 else None


def reap(state_dir: str, older_than_hours: int = 24,
         now: datetime | None = None) -> int:
    """Clear sessions that stopped long ago. Age alone never deletes an active one."""
    now = now or datetime.now(timezone.utc)
    removed = 0
    for f in Path(state_dir).glob("*.json") if Path(state_dir).is_dir() else []:
        try:
            record = json.loads(f.read_text())
        except (json.JSONDecodeError, OSError):
            continue
        if record.get("state") != "stopped":
            continue
        try:
            when = datetime.fromisoformat(record.get("since", ""))
        except (TypeError, ValueError):
            continue
        if (now - when).total_seconds() > older_than_hours * 3600:
            f.unlink(missing_ok=True)
            removed += 1
    return removed


def collect(runner: Runner, root: str,
            state_dir: str = agents_mod.DEFAULT_STATE_DIR) -> dict:
    started = time.monotonic()
    reap(state_dir)
    base = gitsrc.default_branch(runner, root)
    trees = gitsrc.list_worktrees(runner, root)

    sessions = agents_mod.read_state_dir(state_dir)
    panes = agents_mod.tmux_panes(runner)

    for t in trees:
        t.ahead, t.behind = gitsrc.ahead_behind(runner, t.path, base)
        t.dirty = gitsrc.dirty_counts(runner, t.path)

    repo = ghsrc.origin_repo(runner, root)
    if repo:
        prs, pr_status = ghsrc.fetch_prs(runner, root, repo)
        issues, issue_status = ghsrc.fetch_issues(runner, root, repo)
    else:
        prs, issues = [], []
        pr_status = issue_status = ghsrc.SourceStatus(
            "gh", False, "could not resolve a github repo from the origin remote")

    by_branch = {p.branch: p.number for p in prs}
    tree_dicts = []
    for t in trees:
        a = agents_mod.agent_for(t.path, sessions, panes)
        tree_dicts.append({
            "dir": t.dir, "path": t.path, "branch": t.branch, "head": t.head,
            "ahead": t.ahead, "behind": t.behind, "dirty": asdict(t.dirty),
            "agent": asdict(a), "pr": by_branch.get(t.branch or ""),
        })

    parent = _worktree_parent(trees, root)
    return {
        "schema": SCHEMA_VERSION,
        "generated_at": _now_iso(),
        "duration_ms": int((time.monotonic() - started) * 1000),
        "repos": [{
            "name": os.path.basename(root.rstrip("/")),
            "root": root,
            "issue_repo": repo,
            "default_branch": base,
            "worktrees": tree_dicts,
            "prs": [asdict(p) for p in prs],
            "issues": [asdict(i) for i in issues],
            "collisions": gitsrc.collisions(runner, trees, base),
            "commits": [asdict(c) for c in gitsrc.recent_commits(runner, root)],
            "flags": find_flags(trees, prs, parent),
            "sources": [
                asdict(ghsrc.SourceStatus("git", True)),
                asdict(pr_status),
                asdict(ghsrc.SourceStatus("hooks", True) if sessions
                       else ghsrc.SourceStatus("hooks", False, "no session state files found")),
                asdict(ghsrc.SourceStatus("tmux", bool(panes),
                                          None if panes else "no tmux server")),
            ],
        }],
    }
