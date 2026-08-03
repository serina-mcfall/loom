# loom_cli.py
"""Loom's command line. Argument parsing only — the logic lives in the package."""
from __future__ import annotations

import json
import os
import sys
from typing import Callable

from loom.agents import DEFAULT_STATE_DIR
from loom.collect import collect
from loom.rank import needs_you
from loom.runner import SubprocessRunner

USAGE = """usage: loom <command> [options]

  snapshot [--all] [--json]   print the current fleet snapshot
  serve [--port N] [--all]    run the dashboard on 127.0.0.1
  install-hooks               write Loom's hooks into Claude Code settings
"""

LAUNCHPAD = os.path.expanduser("~/Launchpad")


def discover_repos(base: str,
                   listdir: Callable[[str], list[str]] = os.listdir,
                   isdir: Callable[[str], bool] = os.path.isdir) -> list[str]:
    found = []
    try:
        entries = sorted(listdir(base))
    except OSError:
        return []
    for name in entries:
        path = os.path.join(base, name)
        # A repo is a child directory whose own ".git" entry is present. Checked via
        # the injected isdir on the ".git" path itself, not by listing the child —
        # discover_repos only walks ~/Launchpad's immediate children (plain clones),
        # never the linked worktrees nested a level below, so the ".git is a file"
        # trap documented in Task 6's find_flags does not apply here.
        if isdir(os.path.join(path, ".git")):
            found.append(path)
    return found


def repo_roots(all_repos: bool) -> list[str]:
    if all_repos:
        return discover_repos(LAUNCHPAD)
    runner = SubprocessRunner()
    r = runner.run(["git", "rev-parse", "--path-format=absolute", "--git-common-dir"],
                   cwd=os.getcwd())
    if r.ok and r.stdout.strip():
        # The common dir is `<repo>/.git`; the repo root is its parent, and that is ONE
        # dirname, not two. Verified: an earlier version stripped `/.git` AND took a
        # dirname, resolving to the container above the repo, so the default mode
        # reported an empty fleet and Task 8's own acceptance check failed on first run.
        return [os.path.dirname(r.stdout.strip().rstrip("/"))]
    return [os.getcwd()]


def build_snapshot(all_repos: bool, include_gh: bool = True) -> dict:
    runner = SubprocessRunner()
    repos = []
    for root in repo_roots(all_repos):
        snap = collect(runner, root, DEFAULT_STATE_DIR, include_gh=include_gh)
        for repo in snap["repos"]:
            repo["needs_you"] = needs_you(repo)
            repos.append(repo)
    return {"schema": 1, "repos": repos}


def render_text(snapshot: dict) -> str:
    lines = []
    for repo in snapshot["repos"]:
        lines.append(f"{repo['name']} — {len(repo['worktrees'])} trees, "
                     f"{len(repo['prs'])} PRs, {len(repo['issues'])} issues")
        broken = [s for s in repo["sources"] if not s["ok"]]
        for s in broken:
            lines.append(f"  ! {s['name']} unavailable — {s['error']}")
        if not repo["needs_you"]:
            lines.append("  nothing needs you")
        for item in repo["needs_you"]:
            lines.append(f"  [{item['rank']}] {item['subject']} — {item['detail']}")
        lines.append("")
    return "\n".join(lines)


def main(argv: list[str]) -> int:
    if not argv:
        print(USAGE)
        return 2
    command, *rest = argv
    if command == "snapshot":
        snapshot = build_snapshot("--all" in rest)
        print(json.dumps(snapshot, indent=2) if "--json" in rest else render_text(snapshot))
        return 0
    if command == "serve":
        from loom.serve import run_server
        port = int(rest[rest.index("--port") + 1]) if "--port" in rest else 8787
        return run_server(port=port, all_repos="--all" in rest)
    if command == "install-hooks":
        from loom.hookinstall import install
        return install()
    print(USAGE)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
