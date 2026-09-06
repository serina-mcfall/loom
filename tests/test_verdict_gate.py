"""scripts/verdict_gate.py, exercised against real git repositories.

This issue (#14) is about real git topology -- a mock would just assert this
plan's own assumptions back at itself, so every fixture here is a real `git
init`, real commits, and real subprocess calls against them, never a stubbed
Runner.
"""

import json
import os
import subprocess
import tempfile
import unittest
from unittest import mock

from scripts.verdict_gate import check

VERDICT_PATH = ".superpowers/verdict.json"


def _git(args, cwd, check_call=True):
    return subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True, check=check_call,
    )


def _init_repo(path):
    # `-b main` explicitly, not whatever `init.defaultBranch` happens to be
    # configured to on the machine running this test -- step 2's own
    # divergence logic resolves a branch literally named "main" as its
    # fallback, so leaving this implicit would make fixtures (a)/(b)/(c)
    # below depend on host git config rather than on what they say they test.
    _git(["init", "-q", "-b", "main"], path)
    _git(["config", "user.email", "test@example.test"], path)
    _git(["config", "user.name", "Test"], path)
    _git(["config", "commit.gpgsign", "false"], path)


def _write(path, rel, content):
    full = os.path.join(path, rel)
    os.makedirs(os.path.dirname(full), exist_ok=True)
    with open(full, "w") as f:
        f.write(content)


def _commit(path, message):
    _git(["add", "-A"], path)
    _git(["commit", "-q", "--allow-empty", "-m", message], path)
    return _git(["rev-parse", "HEAD"], path).stdout.strip()


def _write_verdict(path, sha, state="READY", reason=None):
    v = {"state": state, "sha": sha}
    if reason is not None:
        v["reason"] = reason
    _write(path, VERDICT_PATH, json.dumps(v))


class VerdictGateRealRepoTests(unittest.TestCase):
    """All eight cases from the plan's ALREADY TRUE section."""

    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.repo = self._td.name
        _init_repo(self.repo)

    def tearDown(self):
        self._td.cleanup()

    def test_absent_verdict_json_blocks(self):
        head = _commit(self.repo, "first")
        code, msg = check(self.repo, head)
        self.assertEqual(code, 1)
        self.assertIn(f"no {VERDICT_PATH} in this branch.", msg)

    def test_malformed_json_blocks_without_raising(self):
        head = _commit(self.repo, "first")
        _write(self.repo, VERDICT_PATH, "{not valid json")
        # If block()'s own return were ever dropped from this except-branch,
        # `state, sha = v.get(...)` runs next with `v` unassigned -- a
        # NameError, not a clean block. Getting a (code, msg) pair back at
        # all, rather than an exception propagating out of check(), is the
        # assertion that matters here.
        code, msg = check(self.repo, head)
        self.assertEqual(code, 1)
        self.assertIn("is not readable JSON", msg)

    def test_state_not_ready_blocks_and_names_reason(self):
        head = _commit(self.repo, "first")
        _write_verdict(self.repo, head, state="BLOCKED", reason="tests failing")
        code, msg = check(self.repo, head)
        self.assertEqual(code, 1)
        self.assertIn("verdict state is 'BLOCKED': tests failing", msg)

    def test_diff_subprocess_raising_blocks(self):
        first = _commit(self.repo, "first")
        second = _commit(self.repo, "second")
        _write_verdict(self.repo, first)
        # A real, unstubbed OS-level failure -- not a mock of git's return
        # value. Clearing PATH means the `git diff` subprocess call itself
        # cannot find git and raises FileNotFoundError, covering the one
        # case that is a Python exception rather than a git topology answer.
        with mock.patch.dict(os.environ, {"PATH": "/does/not/exist"}):
            code, msg = check(self.repo, second)
        self.assertEqual(code, 1)
        self.assertIn("could not diff", msg)

    def test_sha_unreachable_from_head_blocks(self):
        head = _commit(self.repo, "first")
        # A sha that is syntactically valid and really exists -- just in a
        # wholly separate repository, never fetched into this one. This
        # repo's object database genuinely does not have it.
        with tempfile.TemporaryDirectory() as other:
            _init_repo(other)
            foreign_sha = _commit(other, "unrelated, never fetched into self.repo")
        _write_verdict(self.repo, foreign_sha)
        code, msg = check(self.repo, head)
        self.assertEqual(code, 1)
        self.assertIn("is not reachable from this PR's head", msg)

    def test_reviewed_then_diverged_on_this_branch_keeps_existing_message(self):
        """Step 2, fixture (b): a branch that recorded its OWN verdict
        earlier in its own unique history, then landed more commits on the
        SAME branch afterward -- mirrors this exact session's real #11
        experience. Must keep printing the pre-existing message unchanged,
        proving the new divergence check adds coverage without breaking the
        one case issue #14 itself says must keep working.
        """
        _commit(self.repo, "main tip")  # feature diverges from here
        _git(["checkout", "-q", "-b", "feature"], self.repo)
        _write(self.repo, "a.txt", "one")
        reviewed = _commit(self.repo, "reviewed on feature")
        _write_verdict(self.repo, reviewed)
        _commit(self.repo, "record the verdict")
        _write(self.repo, "a.txt", "two")
        head = _commit(self.repo, "more work on the same branch, after review")
        code, msg = check(self.repo, head)
        self.assertEqual(code, 1)
        self.assertIn("file(s) changed since", msg)
        self.assertIn("The review does not cover this code", msg)
        self.assertNotIn("has never been reviewed", msg)

    def test_never_reviewed_when_verdict_predates_this_branch(self):
        """Step 2, fixture (a): mirrors the issue's own example almost
        exactly -- "main carries READY for ec65092 (issue #3)". main's OWN
        tracked verdict.json already names some other, unrelated commit at
        the point this branch was cut. The new branch has never itself been
        reviewed, and this must print the NEW message, not the old generic
        one.
        """
        main_tip = _commit(self.repo, "main's own reviewed commit")
        _write_verdict(self.repo, main_tip)
        _commit(self.repo, "main records its own verdict")
        _git(["checkout", "-q", "-b", "feature"], self.repo)
        _write(self.repo, "b.txt", "this branch's own new work")
        head = _commit(self.repo, "this branch's own first commit")
        # verdict.json is untouched here -- inherited wholesale from main,
        # exactly as issue #14 describes a brand-new branch inheriting it.
        code, msg = check(self.repo, head)
        self.assertEqual(code, 1)
        self.assertIn("This branch has never been reviewed", msg)
        self.assertIn("predates this branch's own commits", msg)
        self.assertNotIn("The review does not cover this code", msg)

    def test_indeterminate_when_divergence_point_cannot_be_computed(self):
        """Step 2, fixture (c): built the same way loom/gitsrc.py's own
        test_touched_files_is_none_when_the_merge_base_cannot_be_found
        fixture is -- two real, disjoint histories in one repository, so
        merge-base against "main" genuinely cannot be computed. Must print
        the NEW indeterminate message, never silently falling into fixture
        (b)'s message.
        """
        _commit(self.repo, "main, its own root commit")
        _git(["checkout", "-q", "--orphan", "feature"], self.repo)
        _write(self.repo, "c.txt", "feature's own unrelated history")
        reviewed = _commit(self.repo, "reviewed on feature's own history")
        _write_verdict(self.repo, reviewed)
        _commit(self.repo, "record the verdict")
        _write(self.repo, "c.txt", "more feature work")
        head = _commit(self.repo, "further, unrelated change")
        code, msg = check(self.repo, head)
        self.assertEqual(code, 1)
        self.assertIn(
            "could not determine this branch's divergence point from main", msg
        )
        self.assertNotIn("has never been reviewed", msg)
        self.assertNotIn("The review does not cover this code", msg)

    def test_only_verdict_file_changed_since_is_open(self):
        reviewed = _commit(self.repo, "first, reviewed here")
        _write_verdict(self.repo, reviewed)
        head = _commit(self.repo, "record the verdict, nothing else")
        code, msg = check(self.repo, head)
        self.assertEqual(code, 0)
        self.assertTrue(msg.startswith("OPEN"))

    def test_sha_equals_head_is_open(self):
        head = _commit(self.repo, "first")
        _write_verdict(self.repo, head)
        code, msg = check(self.repo, head)
        self.assertEqual(code, 0)
        self.assertIn(f"READY verdict matches head {head[:8]}", msg)


if __name__ == "__main__":
    unittest.main()
