# loom_cli.py
"""Loom's command line. Argument parsing only — the logic lives in the package."""
from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timezone
from typing import Callable

from loom.agents import DEFAULT_STATE_DIR
from loom.collect import collect, SCHEMA_VERSION
from loom.view import finalise
from loom.runner import Runner, SubprocessRunner

USAGE = """usage: loom <command> [options]

  snapshot [--all] [--json]   print the current fleet snapshot
  serve [--port N] [--all]    run the dashboard on 127.0.0.1
  install-hooks               write Loom's hooks into Claude Code settings
"""

LAUNCHPAD = os.path.expanduser("~/Launchpad")


def discover_repos(base: str,
                   listdir: Callable[[str], list[str]] = os.listdir) -> list[str]:
    found = []
    try:
        entries = sorted(listdir(base))
    except OSError:
        return []
    for name in entries:
        path = os.path.join(base, name)
        # Test for the ENTRY, never its type: a linked worktree's .git is a file, not
        # a directory, so isdir(child/.git) would silently skip it. This matches
        # find_flags in loom/collect.py, which tests presence for the same reason —
        # two functions answering "is this a git checkout?" must agree on the rule.
        try:
            if ".git" in listdir(path):
                found.append(path)
        except OSError:
            continue
    return found


def repo_roots(all_repos: bool, runner: Runner | None = None) -> list[str]:
    if all_repos:
        return discover_repos(LAUNCHPAD)
    runner = runner or SubprocessRunner()
    r = runner.run(["git", "rev-parse", "--path-format=absolute", "--git-common-dir"],
                   cwd=os.getcwd())
    common_dir = r.stdout.strip().rstrip("/") if r.ok else ""
    # `--path-format=absolute` was requested but not verified: a relative path here
    # would make dirname() silently produce "", and every later cwd-relative git call
    # would then target somewhere unintended with no error. Treat non-absolute as a
    # failed lookup.
    if r.ok and common_dir and os.path.isabs(common_dir):
        # For a worktree or plain clone the common dir is `<repo>/.git`, so the repo
        # root is its parent — ONE dirname, not two. Verified: an earlier version
        # stripped `/.git` AND took a dirname unconditionally, resolving to the
        # container above the repo, so the default mode reported an empty fleet and
        # Task 8's own acceptance check failed on first run.
        #
        # A bare repo's common dir has no trailing `.git` to strip — it IS the repo
        # root already. Taking dirname() unconditionally would climb one level too
        # high for it too, so only strip when the basename says there is a `.git`
        # component to remove.
        if os.path.basename(common_dir) == ".git":
            return [os.path.dirname(common_dir)]
        return [common_dir]
    return [os.getcwd()]


def parse_port(rest: list[str]) -> int:
    """Validate --port's value before anything downstream (e.g. loom.serve) runs.

    Raises ValueError with a message fit to print directly — a missing value or a
    non-integer must exit cleanly with code 2, never a raw traceback.
    """
    idx = rest.index("--port")
    try:
        value = rest[idx + 1]
    except IndexError:
        raise ValueError("--port requires a value")
    try:
        port = int(value)
    except ValueError:
        raise ValueError(f"--port value must be an integer, got {value!r}")
    if not (1 <= port <= 65535):
        raise ValueError(f"--port must be between 1 and 65535, got {port}")
    return port


def build_snapshot(all_repos: bool, include_gh: bool = True,
                   runner: Runner | None = None) -> dict:
    """Collect every repo into one snapshot. Deliberately does NOT rank.

    Ranking is `loom.rank.rank_snapshot`'s job and belongs at the boundary that
    publishes the snapshot, because `serve` mutates `prs` after this returns --
    see rank_snapshot's docstring and audit finding H1. A snapshot from here is
    unranked on purpose; `needs_you` is absent rather than empty, so a consumer
    that forgot to rank fails loudly instead of showing a quiet fleet.
    """
    started = time.monotonic()
    runner = runner or SubprocessRunner()
    repos = []
    for root in repo_roots(all_repos, runner):
        snap = collect(runner, root, DEFAULT_STATE_DIR, include_gh=include_gh)
        repos.extend(snap["repos"])
    # `generated_at` and `duration_ms` describe the WHOLE build, not one root.
    #
    # `collect()` computes its own pair per root and they were discarded here, so
    # the CLI's JSON -- the loom skill's only input -- carried no timestamp at all,
    # while `serve` re-stamped its own. The skill is instructed "if the snapshot is
    # older than 5 minutes, say so" and could never do it. Two consumers of a
    # schema versioned specifically to stop them drifting. Audit 2026-08-05, H7.
    #
    # Timezone-aware on purpose: a naive stamp gives a zone-dependent age, the
    # same trap loom/agents.py's `_age_seconds` refuses.
    return {
        "schema": SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "duration_ms": int((time.monotonic() - started) * 1000),
        "repos": repos,
    }


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


HELP_FLAGS = {"--help", "-h", "help"}


def main(argv: list[str]) -> int:
    if not argv:
        # Bare `loom` is a misuse, not a help request. Distinct exit codes keep those
        # two apart, because only one of them is an error.
        print(USAGE)
        return 2
    if argv[0] in HELP_FLAGS:
        # An explicit help request is a SUCCESSFUL invocation. Exiting 2 made
        # `loom --help` fail inside any script or Makefile that checks status.
        # Audit 2026-08-05, finding L10.
        print(USAGE)
        return 0
    command, *rest = argv
    if command == "snapshot":
        # finalise last, on the finished snapshot: one boundary for both consumers,
        # so the CLI's JSON and the server's frames cannot drift apart (H7).
        snapshot = finalise(build_snapshot("--all" in rest))
        print(json.dumps(snapshot, indent=2) if "--json" in rest else render_text(snapshot))
        return 0
    if command == "serve":
        port = 8787
        if "--port" in rest:
            try:
                port = parse_port(rest)
            except ValueError as exc:
                print(str(exc))
                return 2
        from loom.serve import run_server
        return run_server(port=port, all_repos="--all" in rest)
    if command == "install-hooks":
        from loom.hookinstall import install
        return install()
    print(USAGE)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
