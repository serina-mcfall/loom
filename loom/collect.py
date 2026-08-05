# loom/collect.py
"""One snapshot, assembled from every source, honest about which ones answered."""
from __future__ import annotations

import json
import os
import time
from dataclasses import asdict, replace
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
               worktree_parents: list[str] | None,
               listdir: Callable[[str], list[str]] = os.listdir,
               isdir: Callable[[str], bool] = os.path.isdir) -> list[dict]:
    """Loose ends: PRs with no worktree, and directories that are no longer one.

    `worktree_parents` is a LIST because a fleet's worktrees need not share one
    parent. It used to be a single value that `_worktree_parent` returned only when
    exactly one candidate existed, which silently disabled the stale-directory scan
    for any fleet spread across two directories. Audit 2026-08-05, finding M3.
    """
    # A BARE STRING HERE FAILS SILENTLY AND MUST NOT BE TOLERATED.
    #
    # `str` is iterable, so passing the old single-parent value would loop over its
    # CHARACTERS -- listdir("/"), listdir("t") -- and produce a plausible empty
    # result instead of an error. When this parameter changed from `str` to
    # `list[str]`, seven existing tests kept passing for exactly that reason: they
    # assert an empty list, and character-iteration happened to produce one. Only
    # the single test expecting a flag caught it.
    #
    # A wrong answer that looks like a right one is the failure mode this whole
    # project refuses, so this converts it into a loud one.
    if isinstance(worktree_parents, str):
        raise TypeError(
            "worktree_parents must be a list of paths, not a string: "
            f"{worktree_parents!r} would be iterated character by character")

    flags: list[dict] = []
    branches = {t.branch for t in trees if t.branch}

    for p in prs:
        if p.branch not in branches:
            flags.append({"kind": "orphan_pr", "severity": "warn",
                          "subject": f"PR #{p.number}",
                          "detail": f"branch {p.branch} has no worktree"})

    known = {t.dir for t in trees}
    seen: set[str] = set()
    for parent in worktree_parents or []:
        try:
            entries = listdir(parent)
        except OSError:
            entries = []
        for name in sorted(entries):
            if name.startswith(".") or name in known or name in seen:
                continue
            full = os.path.join(parent, name)
            if not isdir(full):
                continue
            try:
                inner = listdir(full)
            except OSError:
                inner = []
            if ".git" in inner:
                continue
            seen.add(name)
            flags.append({"kind": "stale_dir", "severity": "warn", "subject": name,
                          "detail": f"{name} is not a git worktree"})
    return flags


def _worktree_parents(trees: list[gitsrc.Worktree], root: str) -> list[str]:
    """Every distinct directory that holds a worktree, except the repo's own.

    The repo's own parent is excluded because the main checkout sits beside
    unrelated sibling projects (all of ~/Launchpad, for this fleet), and scanning
    there would flag every one of them as a stale directory.
    """
    own = os.path.dirname(root.rstrip("/"))
    return sorted({os.path.dirname(t.path.rstrip("/")) for t in trees
                   if os.path.dirname(t.path.rstrip("/")) != own})


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
            if when.tzinfo is None:
                continue
            if (now - when).total_seconds() > older_than_hours * 3600:
                f.unlink(missing_ok=True)
                removed += 1
        except (TypeError, ValueError):
            continue
    return removed


def collect(runner: Runner, root: str,
            state_dir: str = agents_mod.DEFAULT_STATE_DIR,
            include_gh: bool = True) -> dict:
    started = time.monotonic()
    reap(state_dir)
    base, base_resolved = gitsrc.default_branch(runner, root)
    trees = gitsrc.list_worktrees(runner, root)

    sessions = agents_mod.read_state_dir(state_dir)
    panes = agents_mod.tmux_panes(runner)

    # ONE `git status` PER WORKTREE, feeding both the dirty counts and the collisions
    # path set. Asking twice was two extra processes per worktree per tick for
    # information already in hand -- audit finding M4.
    statuses = {t.path: gitsrc.worktree_status(runner, t.path) for t in trees}

    for t in trees:
        # None from either source means CANNOT TELL, and is carried through to the
        # snapshot as null rather than flattened to 0 -- see gitsrc and audit
        # finding H3. `sources` names the affected worktrees below.
        ab = gitsrc.ahead_behind(runner, t.path, base)
        t.ahead, t.behind = ab if ab is not None else (None, None)
        s = statuses[t.path]
        t.dirty = s.dirty if s is not None else None

    unmeasured = sorted(t.dir for t in trees
                        if t.ahead is None or t.behind is None or t.dirty is None)

    repo = ghsrc.origin_repo(runner, root)
    if not include_gh:
        # Skip the gh calls entirely rather than fetch-and-discard: the whole point
        # of this flag is to avoid the network call. Report not-fetched, never ok=True
        # — an empty list must never be mistaken for "zero open PRs".
        prs: list[ghsrc.PullRequest] = []
        issues: list[ghsrc.Issue] = []
        not_fetched = "not fetched this cycle"
        pr_status = ghsrc.SourceStatus("gh:prs", False, not_fetched)
        issue_status = ghsrc.SourceStatus("gh:issues", False, not_fetched)
    else:
        if repo:
            prs, pr_status = ghsrc.fetch_prs(runner, root, repo)
            issues, issue_status = ghsrc.fetch_issues(runner, root, repo)
            pr_status = replace(pr_status, name="gh:prs")
            issue_status = replace(issue_status, name="gh:issues")
        else:
            prs, issues = [], []
            no_repo = "could not resolve a github repo from the origin remote"
            pr_status = ghsrc.SourceStatus("gh:prs", False, no_repo)
            issue_status = ghsrc.SourceStatus("gh:issues", False, no_repo)

    by_branch = {p.branch: p.number for p in prs}
    tree_by_branch = {t.branch: t.dir for t in trees if t.branch}
    tree_dicts = []
    now = datetime.now(timezone.utc).astimezone()
    for t in trees:
        # One clock for the whole snapshot: two worktrees must never be aged
        # against different instants, or the same session could read live in
        # one row and stale in the next.
        a = agents_mod.agent_for(t.path, sessions, panes, now)
        tree_dicts.append({
            "dir": t.dir, "path": t.path, "branch": t.branch, "head": t.head,
            "ahead": t.ahead, "behind": t.behind,
            "dirty": asdict(t.dirty) if t.dirty is not None else None,
            "agent": asdict(a), "pr": by_branch.get(t.branch or ""),
        })

    pr_dicts = []
    for p in prs:
        d = asdict(p)
        d["worktree"] = tree_by_branch.get(p.branch)
        pr_dicts.append(d)

    parents = _worktree_parents(trees, root)
    found_collisions, undetermined = gitsrc.collisions(runner, trees, base, statuses)
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
            "prs": pr_dicts,
            "issues": [asdict(i) for i in issues],
            "collisions": found_collisions,
            "commits": [asdict(c) for c in gitsrc.recent_commits(runner, root)],
            "flags": find_flags(trees, prs, parents),
            "sources": [
                asdict(ghsrc.SourceStatus("git", True)),
                asdict(ghsrc.SourceStatus(
                    "git:default-branch", base_resolved,
                    None if base_resolved else
                    f"could not resolve origin/HEAD; falling back to a {base!r} guess")),
                # Per-fact honesty for the worktrees and collisions panels.
                # `sources` reported at subsystem granularity only -- one `git`
                # entry, hardcoded True -- so a per-worktree git failure showed up
                # nowhere and rendered as a confident 0. These two entries are the
                # honesty channel for exactly that. Audit 2026-08-05, finding H3.
                asdict(ghsrc.SourceStatus(
                    "git:worktree-facts", not unmeasured,
                    None if not unmeasured else
                    f"could not measure ahead/behind or dirty counts for "
                    f"{len(unmeasured)} worktree(s): {', '.join(unmeasured)}")),
                asdict(ghsrc.SourceStatus(
                    "git:collisions", not undetermined,
                    None if not undetermined else
                    f"could not enumerate changed files for {len(undetermined)} "
                    f"worktree(s), so they are absent from the matrix: "
                    f"{', '.join(undetermined)}")),
                asdict(pr_status),
                asdict(issue_status),
                asdict(ghsrc.SourceStatus("hooks", True)),
                asdict(ghsrc.SourceStatus("tmux", bool(panes),
                                          None if panes else "no tmux server")),
            ],
        }],
    }
