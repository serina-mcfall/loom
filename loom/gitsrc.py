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


def touched_files(runner: Runner, path: str, base: str) -> set[str]:
    """Files this worktree has changed: committed since the merge-base, plus uncommitted."""
    files: set[str] = set()
    mb = runner.run(["git", "merge-base", base, "HEAD"], cwd=path)
    if mb.ok and mb.stdout.strip():
        d = runner.run(["git", "diff", "--name-only", mb.stdout.strip(), "HEAD"], cwd=path)
        if d.ok:
            files.update(f for f in d.stdout.splitlines() if f)
    s = runner.run(["git", "status", "--porcelain=v1"], cwd=path)
    if s.ok:
        for line in s.stdout.splitlines():
            if len(line) > 3:
                files.add(line[3:].strip())
    return files


def collisions(runner: Runner, trees: list[Worktree], base: str) -> list[dict]:
    by_file: dict[str, set[str]] = {}
    for tree in trees:
        label = tree.branch or tree.dir
        for f in touched_files(runner, tree.path, base):
            by_file.setdefault(f, set()).add(label)
    return [{"file": f, "branches": sorted(b)}
            for f, b in sorted(by_file.items()) if len(b) > 1]
