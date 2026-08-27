"""Tokens and notional cost, read from Claude Code's own local transcripts.

Loom never asks Claude Code for this — Claude Code already writes every
session's usage to ~/.claude/projects/<slug>/<session_id>.jsonl, and the hook
(hooks/loom_hook.py) deliberately does not record the transcript path itself
("A local web server must never become a place a transcript can leak from").
So this module re-derives the transcript's location from the same `cwd` and
`session_id` the hook already writes, and reads usage straight off disk.
"""
from __future__ import annotations

import re
from pathlib import Path


def locate_transcript(home: str, cwd: str, session_id: str) -> Path | None:
    """The .jsonl transcript path for one session, or None if it isn't there.

    Builds the slug the same way Claude Code does: every character in `cwd`
    that isn't a-z, A-Z or 0-9 becomes "-", and nothing is prepended — `cwd`
    already begins with "/". Verified 2026-08-23 against all 42 project
    directories on this machine that carry a readable `cwd`: this rule
    matched 42 of 42 (see the plan's ALREADY TRUE section for the wrong rule
    this replaced and why its failure was silent).

    `cwd` MUST already be the session's resolved (realpath) cwd — measured
    2026-08-27 live against a real symlinked directory: Claude Code resolves
    cwd before slugifying, so a raw, unresolved cwd here would derive a slug
    that is never created and this would return None forever for every
    symlinked worktree. Resolving is the caller's job (worktree_cost, step
    4); this function only slugifies whatever string it is given.
    """
    slug = re.sub(r"[^a-zA-Z0-9]", "-", cwd)
    path = Path(home, ".claude", "projects", slug, f"{session_id}.jsonl")
    return path if path.is_file() else None
