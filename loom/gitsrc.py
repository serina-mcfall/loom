"""Facts git can tell us about a fleet of worktrees."""
from __future__ import annotations

import os
from dataclasses import dataclass, field

from .runner import Runner


@dataclass(frozen=True)
class Dirty:
    staged: int = 0
    unstaged: int = 0
    untracked: int = 0

    @property
    def total(self) -> int:
        return self.staged + self.unstaged + self.untracked


@dataclass
class Worktree:
    path: str
    dir: str
    branch: str | None
    head: str
    ahead: int = 0
    behind: int = 0
    dirty: Dirty = field(default_factory=Dirty)


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


def default_branch(runner: Runner, root: str) -> str:
    r = runner.run(["git", "symbolic-ref", "--short", "refs/remotes/origin/HEAD"], cwd=root)
    if r.ok and "/" in r.stdout:
        return r.stdout.strip().split("/", 1)[1]
    return "main"


def ahead_behind(runner: Runner, path: str, base: str) -> tuple[int, int]:
    """Returns (ahead, behind). git prints left=base-only=behind, right=ours=ahead."""
    r = runner.run(["git", "rev-list", "--left-right", "--count", f"{base}...HEAD"], cwd=path)
    if not r.ok:
        return (0, 0)
    parts = r.stdout.split()
    if len(parts) != 2:
        return (0, 0)
    behind, ahead = int(parts[0]), int(parts[1])
    return (ahead, behind)


def dirty_counts(runner: Runner, path: str) -> Dirty:
    r = runner.run(["git", "status", "--porcelain=v1"], cwd=path)
    if not r.ok:
        return Dirty()
    staged = unstaged = untracked = 0
    for line in r.stdout.splitlines():
        if len(line) < 2:
            continue
        x, y = line[0], line[1]
        if x == "?" and y == "?":
            untracked += 1
            continue
        if x not in " ?":
            staged += 1
        if y not in " ?":
            unstaged += 1
    return Dirty(staged, unstaged, untracked)
