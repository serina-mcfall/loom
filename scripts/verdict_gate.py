#!/usr/bin/env python3
"""Is there a READY verdict, and does it cover the head commit?

Extracted from .github/workflows/checks.yml's `verdict` job -- see
docs/plans/2026-09-06-issue-14-stale-verdict-gate.md, step 1. This step
changes NO behaviour: every message string, every exit code, and all eight
cases the inline YAML handled are preserved byte-for-byte. The only change is
shape -- `check()` RETURNS (exit_code, message) instead of printing and
calling sys.exit() directly, so a test can assert on the message without
capturing stdout. `main()` is the thin CLI wrapper checks.yml calls.

WHAT THIS CHECK CAN AND CANNOT PROVE

It proves a READY verdict was recorded for this exact commit. It does NOT
prove the review was any good -- the verdict is a recorded judgement, and no
script can re-derive judgement. Its value is narrower and still real: a
review that never happened, or happened against earlier code, cannot satisfy
it, and any new push invalidates it automatically.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys

VERDICT_PATH = ".superpowers/verdict.json"


def check(repo_root: str, head_sha: str, verdict_path: str = VERDICT_PATH) -> tuple[int, str]:
    """Return (exit_code, message) -- 0 = open, 1 = blocked. Never raises for
    a missing or malformed verdict file; that is exactly what this checks for.
    """
    path = os.path.join(repo_root, verdict_path)
    want = head_sha

    def block(msg: str) -> tuple[int, str]:
        # THE REMEDIATION MUST NAME SOMETHING THAT EXISTS.
        #
        # This used to say `.claude/skills/review-final/verdict.sh`, a path
        # that does not exist in this repository -- `.claude/` holds one
        # gitignored stamp file. A contributor hitting this gate followed the
        # instructions to a missing script, and a gate whose escape hatch is
        # undocumented is a gate people work around. Audit 2026-08-05, M6.
        #
        # No path is named now, deliberately: the script ships inside the
        # serina-skills plugin, whose cache directory is VERSION-specific
        # (serina/0.6.0/skills/review-final/verdict.sh today, something else
        # after the next update). Any literal path here would rot. The skill
        # knows where its own script lives, so the instruction is to invoke
        # the skill.
        lines = [
            f"BLOCKED  {msg}",
            "",
            "This branch has no review recorded for its current state.",
            "  1. Run the review-final skill (serina:review-final).",
            "  2. Ask it to record the verdict:  verdict.sh record ready",
            "     -- it re-runs the objective checks and REFUSES to write",
            "        READY if they fail, so a claim cannot outrun the tests.",
            "  3. Commit .superpowers/verdict.json and push.",
            "",
            "verdict.sh ships with the skill, not with this repo.",
        ]
        return 1, "\n".join(lines)

    # Absence blocks. A review killed by turn exhaustion writes nothing, and
    # nothing must never read as approval.
    if not os.path.exists(path):
        return block(f"no {verdict_path} in this branch.")

    try:
        v = json.load(open(path))
    except Exception as exc:
        return block(f"{verdict_path} is not readable JSON ({exc}).")

    state, sha = v.get("state"), v.get("sha")

    if state != "READY":
        reason = v.get("reason")
        return block(f"verdict state is {state!r}" + (f": {reason}" if reason else ""))

    # THE CHICKEN-AND-EGG, and why an exact match alone cannot work.
    #
    # verdict.sh stamps the sha of the commit it reviewed. Committing the
    # verdict file then creates a NEW head -- so an exact-match rule can
    # never be satisfied by anyone, ever. The first green run is impossible.
    #
    # The fix is not to loosen the comparison but to make it precise: the
    # head may differ from the reviewed sha ONLY if the sole change between
    # them is the verdict file itself. Any other file touched after the
    # review means the review does not cover the code, and it blocks.
    if sha != want:
        try:
            changed = subprocess.run(
                ["git", "diff", "--name-only", f"{sha}..{want}"],
                capture_output=True, text=True, timeout=30, cwd=repo_root,
            )
        except Exception as exc:
            return block(f"could not diff {str(sha)[:8]}..{want[:8]} ({exc}).")

        if changed.returncode != 0:
            # An unknown sha lands here. Refusing is correct: a verdict
            # naming a commit this branch does not contain proves nothing.
            return block(
                f"verdict names {str(sha)[:8]}, which is not reachable from "
                f"this PR's head {want[:8]}.\n"
                f"         git said: {changed.stderr.strip()[:120]}"
            )

        files = [f for f in changed.stdout.split("\n") if f.strip()]
        if files != [verdict_path]:
            return block(
                f"verdict is for {str(sha)[:8]} but head is {want[:8]}, and "
                f"{len(files)} file(s) changed since:\n"
                + "\n".join(f"           {f}" for f in files[:10])
                + "\n         The review does not cover this code."
            )
        lines = [
            f"OPEN  verdict is for {str(sha)[:8]}; the only change since is "
            "the verdict file itself"
        ]
    else:
        lines = [f"OPEN  READY verdict matches head {want[:8]}"]

    lines.append(
        f"      recorded {v.get('recorded_at', 'at an unstated time')}"
        f" against plan {v.get('plan', '(unnamed)')}"
    )
    checks = v.get("checks") or {}
    if checks:
        lines.append(f"      checks at record time: {checks}")
    return 0, "\n".join(lines)


def main(argv: list[str]) -> int:
    # THE TRAP THIS AVOIDS: on a pull_request event, `github.sha` is the
    # ephemeral MERGE commit GitHub creates, not the commit the author has
    # checked out. verdict.sh records the author's HEAD. Comparing against
    # github.sha would fail every single time, for a reason that looks like
    # the gate working. Always the PR head -- checks.yml sets HEAD_SHA to
    # github.event.pull_request.head.sha, never github.sha.
    repo_root = argv[1] if len(argv) > 1 else "."
    head_sha = os.environ["HEAD_SHA"]
    exit_code, message = check(repo_root, head_sha)
    print(message)
    return exit_code


if __name__ == "__main__":
    sys.exit(main(sys.argv))
