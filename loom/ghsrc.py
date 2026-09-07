"""What GitHub knows, asked for in a way that cannot silently answer about the wrong repo."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from .runner import Runner

# Owner and repository names must each START with an alphanumeric.
#
# WHY THAT MATTERS MORE THAN IT LOOKS: the extracted value is passed straight to
# `gh` as the argument of `-R`, so `--upload-pack=evil/x` would arrive as another
# OPTION rather than as a repository. The design doc flagged this in its own
# threat-model gap table and said "the regex should reject it" -- a stated
# intention that nothing enforced until now. Audit 2026-08-05, finding M2.
#
# GitHub names cannot begin with a hyphen, so this rejects nothing legitimate.
# Inner hyphens, dots and underscores are all still allowed, because real
# repositories are full of them and breaking those would be worse than the hole.
_NAME = r"[A-Za-z0-9][A-Za-z0-9._-]*"
SSH_RE = re.compile(rf"^git@github\.com:(?P<repo>{_NAME}/{_NAME}?)(?:\.git)?$")
HTTPS_RE = re.compile(rf"^https://github\.com/(?P<repo>{_NAME}/{_NAME}?)(?:\.git)?/?$")

PR_FIELDS = "number,title,headRefName,isDraft,reviewDecision,statusCheckRollup,updatedAt,url"
ISSUE_FIELDS = "number,title,labels,assignees,url"
FAILING = {"FAILURE", "TIMED_OUT", "CANCELLED", "ACTION_REQUIRED", "STARTUP_FAILURE", "ERROR"}
GOOD = {"SUCCESS", "NEUTRAL", "SKIPPED"}


@dataclass
class SourceStatus:
    name: str
    ok: bool
    error: str | None = None
    last_good: str | None = None


@dataclass
class PullRequest:
    number: int
    title: str
    branch: str
    draft: bool
    review: str | None
    checks: str
    updated_at: str
    url: str


@dataclass
class Issue:
    number: int
    title: str
    labels: list[str]
    assignees: list[str]
    url: str


def origin_repo(runner: Runner, root: str) -> str | None:
    """owner/repo from the origin remote. Never asks gh to guess."""
    r = runner.run(["git", "remote", "get-url", "origin"], cwd=root)
    if not r.ok:
        return None
    url = r.stdout.strip()
    for pattern in (SSH_RE, HTTPS_RE):
        m = pattern.match(url)
        if m:
            return m.group("repo")
    return None


def remote_reachable_shas(runner: Runner, root: str, since_iso: str) -> list[str] | None:
    """Full shas reachable from ANY remote-tracking ref, no older than
    `since_iso` -- ONE subprocess call, bounded by recency rather than full
    history, the same way `gitsrc.recent_commits()` bounds itself by count
    rather than walking the whole repo.

    Returns `None` on a failed git call -- an honest "could not verify",
    never a guessed empty list, which `commit_url` below treats as "do not
    link" rather than silently trusting an unmeasured state.

    This is what closes the gap `commit_url`'s docstring used to carry as a
    known, undone limitation (found by an independent codex review,
    2026-09-07): `recent_commits()` runs `git log --all`, which includes
    commits on a branch that has never been pushed, and every one used to
    get a GitHub link regardless. The naive fix -- `git merge-base
    --is-ancestor <sha> <ref>` per commit -- costs one subprocess call PER
    COMMIT, up to 40 more per tick, against a budget this project measures
    and tests explicitly (audit 2026-08-05 finding M4,
    `tests/test_collect.py::TestSubprocessBudget`). This function is the
    single-call alternative: one `git rev-list --remotes --since=<date>`
    covers every remote-tracking branch at once, and membership is then a
    plain Python set lookup with no further subprocess cost. `--since`
    bounds the walk to roughly the same window `recent_commits()`'s own
    40-commit limit already implies, so this does not become a full-history
    scan on an old, busy repo.
    """
    r = runner.run(["git", "rev-list", "--remotes", "--since", since_iso], cwd=root)
    if not r.ok:
        return None
    return r.stdout.split()


def commit_reachable(sha: str, remote_shas: list[str] | None) -> bool:
    """Is the abbreviated `sha` a prefix of some full sha `remote_shas`
    reached? `remote_shas is None` (the git call failed) is treated as
    "cannot verify" -- the safe direction is to withhold the link, not to
    guess it is fine. `recent_commits()` never collects a full sha (see
    `gitsrc.LOG_FORMAT`'s `%h`), so this is a prefix match, not equality.
    """
    if remote_shas is None:
        return False
    return any(full.startswith(sha) for full in remote_shas)


def commit_url(issue_repo: str | None, sha: str) -> str | None:
    """A commit's GitHub page, or None with no GitHub remote to point at.

    Unlike a PR or issue, `git log` has no notion of GitHub -- there is no
    `url` field to ask gh for, so this is the one link in the interactivity
    spec that is built rather than fetched. GitHub resolves an abbreviated
    sha (which is all loom/gitsrc.py's `%h` ever collects) in a commit URL,
    so the short sha already on hand is enough IF the commit actually
    reached GitHub -- callers are expected to check `commit_reachable`
    first (see `loom/collect.py`) so this only ever gets called for a
    commit already confirmed to be on some remote-tracking ref.
    """
    if issue_repo is None:
        return None
    return f"https://github.com/{issue_repo}/commit/{sha}"


def derive_checks(rollup: list[dict]) -> str:
    """No checks configured is 'none', which is not the same as 'passing'.

    Uses a whitelist for passing states so unknown states degrade to pending,
    not passing — a tool that reports unknown states as green lies in the one
    direction that matters.
    """
    if not rollup:
        return "none"
    tokens = [(c.get("conclusion") or c.get("state") or "").upper() for c in rollup]
    if any(s in FAILING for s in tokens):
        return "failing"
    if any(c.get("status") not in (None, "COMPLETED") for c in rollup):
        return "pending"
    # Passing only if every token is known-good; unknown states mean pending.
    if all(t in GOOD for t in tokens):
        return "passing"
    return "pending"


def _fetch_json(runner: Runner, root: str, argv: list[str],
                name: str) -> tuple[Any, SourceStatus]:
    """Run a `gh --json` command. Returns (parsed, status); parsed is None on failure.

    `Any` is honest here rather than lazy: this is the boundary where an external
    tool's JSON enters the process, and its shape is whatever `gh` decided to emit.
    The callers immediately narrow it into `PullRequest` / `Issue` and record a
    degraded source for anything that will not fit.
    """
    r = runner.run(argv, cwd=root)
    if not r.ok:
        first = (r.stderr or "unknown error").strip().splitlines()[0]
        return None, SourceStatus(name, False, first)
    try:
        return json.loads(r.stdout or "[]"), SourceStatus(name, True)
    except json.JSONDecodeError as exc:
        return None, SourceStatus(name, False, f"unparseable JSON: {exc}")


def _degrade(name: str, bad_records: list[str]) -> SourceStatus:
    """One SourceStatus for however many records this source failed to parse."""
    detail = bad_records[0] if len(bad_records) == 1 else (
        f"{bad_records[0]} ({len(bad_records)} records affected)")
    return SourceStatus(name, False, detail)


def fetch_prs(runner: Runner, root: str, repo: str) -> tuple[list[PullRequest], SourceStatus]:
    data, status = _fetch_json(runner, root, [
        "gh", "pr", "list", "-R", repo, "--state", "open", "--limit", "50",
        "--json", PR_FIELDS], "gh")
    if data is None:
        return [], status
    prs: list[PullRequest] = []
    bad: list[str] = []
    for p in data:
        try:
            prs.append(PullRequest(
                number=p["number"], title=p["title"], branch=p["headRefName"],
                draft=bool(p.get("isDraft")),
                review=(p.get("reviewDecision") or None),
                checks=derive_checks(p.get("statusCheckRollup") or []),
                updated_at=p.get("updatedAt", ""),
                url=p["url"],
            ))
        except (KeyError, TypeError) as exc:
            bad.append(f"malformed PR record: missing {exc}")
    if bad:
        return prs, _degrade("gh", bad)
    return prs, status


def fetch_issues(runner: Runner, root: str, repo: str) -> tuple[list[Issue], SourceStatus]:
    data, status = _fetch_json(runner, root, [
        "gh", "issue", "list", "-R", repo, "--state", "open", "--limit", "50",
        "--json", ISSUE_FIELDS], "gh")
    if data is None:
        return [], status
    issues: list[Issue] = []
    bad: list[str] = []
    for i in data:
        try:
            issues.append(Issue(
                number=i["number"], title=i["title"],
                labels=[l["name"] for l in i.get("labels") or []],
                assignees=[a["login"] for a in i.get("assignees") or []],
                url=i["url"],
            ))
        except (KeyError, TypeError) as exc:
            bad.append(f"malformed issue record: missing {exc}")
    if bad:
        return issues, _degrade("gh", bad)
    return issues, status
