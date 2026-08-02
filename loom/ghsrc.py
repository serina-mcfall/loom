"""What GitHub knows, asked for in a way that cannot silently answer about the wrong repo."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass

from .runner import Runner

SSH_RE = re.compile(r"^git@github\.com:(?P<repo>[^/]+/[^/]+?)(?:\.git)?$")
HTTPS_RE = re.compile(r"^https://github\.com/(?P<repo>[^/]+/[^/]+?)(?:\.git)?/?$")

PR_FIELDS = "number,title,headRefName,isDraft,reviewDecision,statusCheckRollup,updatedAt"
ISSUE_FIELDS = "number,title,labels,assignees"
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


@dataclass
class Issue:
    number: int
    title: str
    labels: list[str]
    assignees: list[str]


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


def _fetch_json(runner: Runner, root: str, argv: list[str], name: str):
    r = runner.run(argv, cwd=root)
    if not r.ok:
        first = (r.stderr or "unknown error").strip().splitlines()[0]
        return None, SourceStatus(name, False, first)
    try:
        return json.loads(r.stdout or "[]"), SourceStatus(name, True)
    except json.JSONDecodeError as exc:
        return None, SourceStatus(name, False, f"unparseable JSON: {exc}")


def fetch_prs(runner: Runner, root: str, repo: str) -> tuple[list[PullRequest], SourceStatus]:
    data, status = _fetch_json(runner, root, [
        "gh", "pr", "list", "-R", repo, "--state", "open", "--limit", "50",
        "--json", PR_FIELDS], "gh")
    if data is None:
        return [], status
    return [PullRequest(
        number=p["number"], title=p["title"], branch=p["headRefName"],
        draft=bool(p.get("isDraft")),
        review=(p.get("reviewDecision") or None),
        checks=derive_checks(p.get("statusCheckRollup") or []),
        updated_at=p.get("updatedAt", ""),
    ) for p in data], status


def fetch_issues(runner: Runner, root: str, repo: str) -> tuple[list[Issue], SourceStatus]:
    data, status = _fetch_json(runner, root, [
        "gh", "issue", "list", "-R", repo, "--state", "open", "--limit", "50",
        "--json", ISSUE_FIELDS], "gh")
    if data is None:
        return [], status
    return [Issue(
        number=i["number"], title=i["title"],
        labels=[l["name"] for l in i.get("labels") or []],
        assignees=[a["login"] for a in i.get("assignees") or []],
    ) for i in data], status
