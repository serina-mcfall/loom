"""Facts git can tell us about a fleet of worktrees."""
from __future__ import annotations

import os
from dataclasses import dataclass

from .runner import Runner


@dataclass(frozen=True)
class Dirty:
    staged: int = 0
    unstaged: int = 0
    untracked: int = 0


@dataclass
class Worktree:
    path: str
    dir: str
    branch: str | None
    head: str
    # None means CANNOT TELL, never zero. These default to None rather than 0 so
    # a worktree whose facts were never measured is not born looking healthy.
    # Audit 2026-08-05, finding H3.
    ahead: int | None = None
    behind: int | None = None
    dirty: Dirty | None = None


def list_worktrees(runner: Runner, root: str) -> list[Worktree]:
    r = runner.run(["git", "worktree", "list", "--porcelain"], cwd=root)
    if not r.ok:
        return []
    trees: list[Worktree] = []
    path = head = branch = None
    for line in r.stdout.splitlines() + [""]:
        if line.startswith("worktree "):
            path = line[len("worktree "):]
            head, branch = "", None
        elif line.startswith("HEAD "):
            head = line[len("HEAD "):]
        elif line.startswith("branch refs/heads/"):
            branch = line[len("branch refs/heads/"):]
        elif line == "" and path:
            trees.append(Worktree(path=path, dir=os.path.basename(path.rstrip("/")),
                                  branch=branch, head=head or ""))
            path = head = branch = None
    return trees


def default_branch(runner: Runner, root: str) -> tuple[str, bool]:
    """The repo's default branch, and whether it was actually resolved.

    On failure (e.g. `origin/HEAD` was never set) this falls back to a
    `"main"` guess so the rest of the tool still has something to work with,
    but the second element tells the caller the guess is unverified so it can
    be surfaced instead of silently corrupting every downstream comparison.
    """
    r = runner.run(["git", "symbolic-ref", "--short", "refs/remotes/origin/HEAD"], cwd=root)
    if r.ok and "/" in r.stdout:
        return r.stdout.strip().split("/", 1)[1], True
    return "main", False


def ahead_behind(runner: Runner, path: str, base: str) -> tuple[int, int] | None:
    """Returns (ahead, behind), or None when it cannot be determined.

    git prints left=base-only=behind, right=ours=ahead.

    NONE MEANS CANNOT TELL AND MUST NEVER BE READ AS ZERO. This used to return
    (0, 0) on failure, so a worktree 12 ahead whose `git rev-list` failed
    reported exactly what a worktree in perfect sync reports -- and the page
    rendered a confident "0". The same rule `_age_seconds` in loom/agents.py
    already applies to timestamps. Audit 2026-08-05, finding H3.

    The most likely failure is not exotic: when `origin/HEAD` is unresolvable,
    `default_branch` returns a "main" guess, and if that guess is wrong every
    comparison here fails at once.
    """
    r = runner.run(["git", "rev-list", "--left-right", "--count", f"{base}...HEAD"], cwd=path)
    if not r.ok:
        return None
    parts = r.stdout.split()
    if len(parts) != 2:
        return None
    try:
        behind, ahead = int(parts[0]), int(parts[1])
    except ValueError:
        # git always prints two integers here. Anything else means this command
        # did not do what we think it did, and int() would have raised straight
        # out of collect() and killed the whole snapshot.
        return None
    return (ahead, behind)


@dataclass(frozen=True)
class Status:
    """One `git status` answer, serving both the counts and the changed paths."""
    dirty: Dirty
    paths: frozenset[str]


def worktree_status(runner: Runner, path: str) -> Status | None:
    """Counts AND changed paths from a SINGLE `git status`, or None on failure.

    This used to be three calls asking the same working tree about the same
    changes: `git status` for the counts here, then `git diff --name-only HEAD` and
    `git ls-files --others` inside `touched_files` for the paths. At 2-second
    refreshes over a six-worktree fleet that is a lot of processes for one answer.
    Audit 2026-08-05, finding M4.

    `-z` IS REQUIRED, NOT COSMETIC. Without it `--porcelain=v1` quotes any path with
    a space or non-ASCII character, so paths parsed here would silently disagree with
    the ones `git diff -z` returns, and the collisions matrix would compare two
    different spellings of the same file.

    None rather than an empty Status on failure: a clean tree and an unmeasurable one
    differ by whether work is at risk of being lost, which is rank 5's entire job
    (finding H3).

    `-uall` IS REQUIRED, NOT COSMETIC (issue #17). Without it git defaults to
    `-unormal`, which collapses a wholly-new untracked directory to one line
    naming the directory rather than the files inside it -- undercounting
    rank 5's dirty total and, worse, hiding real collisions between two
    worktrees whose files inside a same-named new directory never actually
    collide (or, in the divergent-branch case, missing a genuine collision
    entirely: one worktree already has the directory tracked and reports the
    specific filename, the other's directory is wholly new and collapses, so
    the two never compare equal without `-uall`). Measured cost on the
    largest real checkout on this machine (~Launchpad/buzz, 4.6M files):
    warm-cache steady state costs roughly 1-3 hundredths of a second more per
    worktree -- real, but small, and not worth diverging this call from the
    collisions path (finding M4) over.
    """
    r = runner.run(["git", "status", "--porcelain=v1", "-z", "-uall"], cwd=path)
    if not r.ok:
        return None

    staged = unstaged = untracked = 0
    paths: set[str] = set()

    # `-z` yields NUL-terminated entries, and a rename or copy is TWO tokens: the
    # entry (carrying the NEW path) followed by the ORIGINAL path on its own.
    # Verified against real git output. Failing to consume that second token would
    # parse the old path as a status entry and desynchronise everything after it.
    tokens = [t for t in r.stdout.split("\0") if t]
    i = 0
    while i < len(tokens):
        entry = tokens[i]
        i += 1
        if len(entry) < 3:
            continue
        x, y, name = entry[0], entry[1], entry[3:]
        if x == "?" and y == "?":
            untracked += 1
            paths.add(name)
            continue
        if x in "RC":
            i += 1          # consume the original path; only the new one is reported,
                            # matching `git diff --name-only`'s rename behaviour so the
                            # two sources of collision paths agree.
        if x not in " ?":
            staged += 1
        if y not in " ?":
            unstaged += 1
        paths.add(name)

    return Status(Dirty(staged, unstaged, untracked), frozenset(paths))


LOG_FORMAT = "%x1e%h%x1f%aI%x1f%s%x1f%D"


@dataclass
class Commit:
    when: str
    branch: str
    sha: str
    subject: str
    files: int
    add: int
    dele: int


def _branch_from_decoration(decoration: str) -> str:
    """'HEAD -> feature-c, origin/feature-c' -> 'feature-c'."""
    for part in (p.strip() for p in decoration.split(",")):
        if part.startswith("HEAD -> "):
            return part[len("HEAD -> "):]
    for part in (p.strip() for p in decoration.split(",")):
        if part and not part.startswith(("HEAD", "tag:", "origin/")):
            return part
    return ""


def recent_commits(runner: Runner, root: str, limit: int = 40) -> list[Commit]:
    r = runner.run(
        ["git", "log", "--all", "--no-merges", "-n", str(limit),
         f"--format={LOG_FORMAT}", "--numstat"], cwd=root)
    if not r.ok:
        return []
    commits: list[Commit] = []
    for record in r.stdout.split("\x1e"):
        if not record.strip():
            continue
        head, *stat_lines = record.splitlines()
        fields = head.split("\x1f")
        if len(fields) < 4:
            continue
        sha, when, subject, decoration = fields[0], fields[1], fields[2], fields[3]
        files = add = dele = 0
        for line in stat_lines:
            cols = line.split("\t")
            if len(cols) != 3:
                continue
            files += 1
            add += int(cols[0]) if cols[0].isdigit() else 0
            dele += int(cols[1]) if cols[1].isdigit() else 0
        commits.append(Commit(when, _branch_from_decoration(decoration), sha,
                              subject, files, add, dele))
    return commits


def touched_files(runner: Runner, path: str, base: str,
                  status: Status | None = None) -> set[str] | None:
    """Files this worktree has changed: committed since the merge-base, plus uncommitted.

    Returns None if ANY of the four git calls fails, because a partial set is
    worse than no set: it silently understates what the worktree touched, and the
    collisions matrix built from it then reports "No two worktrees are editing the
    same file" with confidence. Audit 2026-08-05, finding H3.

    Every part is required. Dropping only the failed one would mean a worktree with
    40 committed changes and no uncommitted ones looked like it had touched
    nothing at all.

    Pass `status` to reuse a `worktree_status` already fetched for the dirty counts,
    which is what `collect` does: the uncommitted half of this answer is exactly what
    `git status` already reported, so asking again with `git diff --name-only HEAD`
    and `git ls-files --others` is two extra processes per worktree per tick for
    information already in hand. Audit 2026-08-05, finding M4.

    Omit it and the two calls are made as before, so any caller outside `collect`
    still works unchanged.
    """
    files: set[str] = set()

    mb = runner.run(["git", "merge-base", base, "HEAD"], cwd=path)
    if not mb.ok or not mb.stdout.strip():
        # Includes unrelated histories, and the common case: `base` is
        # default_branch's unverified "main" guess and no such ref exists.
        return None
    d = runner.run(["git", "diff", "--name-only", "-z", mb.stdout.strip(), "HEAD"], cwd=path)
    if not d.ok:
        return None
    files.update(f for f in d.stdout.split("\0") if f)

    if status is not None:
        # Staged, unstaged and untracked, all from the one status call.
        files.update(status.paths)
        return files

    # Tracked changes (staged and unstaged)
    t = runner.run(["git", "diff", "--name-only", "-z", "HEAD"], cwd=path)
    if not t.ok:
        return None
    files.update(f for f in t.stdout.split("\0") if f)

    # Untracked files
    u = runner.run(["git", "ls-files", "--others", "--exclude-standard", "-z"], cwd=path)
    if not u.ok:
        return None
    files.update(f for f in u.stdout.split("\0") if f)

    return files


def collisions(runner: Runner, trees: list[Worktree], base: str,
               statuses: dict[str, Status | None] | None = None
               ) -> tuple[list[dict], list[str]]:
    """Returns (collisions, labels of worktrees that could not be enumerated).

    The second element is the honesty channel. A worktree whose files could not
    be read is left out of the matrix -- there is nothing else to do with it --
    but it must be NAMED, or the matrix reports "no collisions" while one of the
    two branches that actually collide was never compared. Audit 2026-08-05,
    finding H3.

    `statuses` maps a worktree path to its already-fetched `worktree_status`, so the
    uncommitted half of each answer costs nothing extra (finding M4).
    """
    by_file: dict[str, set[str]] = {}
    undetermined: list[str] = []
    for tree in trees:
        label = tree.branch or tree.dir
        touched = touched_files(runner, tree.path, base,
                               (statuses or {}).get(tree.path))
        if touched is None:
            undetermined.append(label)
            continue
        for f in touched:
            by_file.setdefault(f, set()).add(label)
    found = [{"file": f, "branches": sorted(b)}
             for f, b in sorted(by_file.items()) if len(b) > 1]
    return found, undetermined
