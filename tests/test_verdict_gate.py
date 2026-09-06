"""scripts/verdict_gate.py, exercised against real git repositories.

This issue (#14) is about real git topology -- a mock would just assert this
plan's own assumptions back at itself, so every fixture here is a real `git
init`, real commits, and real subprocess calls against them, never a stubbed
Runner.
"""

import json
import os
import subprocess
import sys
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
        self.assertIn("a.txt", msg)  # the actual changed file must be named, not just a count
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

    def test_never_reviewed_when_main_advances_past_divergence_after_branch_cut(self):
        """The actual issue #14 bug, not the equality case above.

        `test_never_reviewed_when_verdict_predates_this_branch` writes the
        verdict for the divergence point ITSELF -- a sha equal to
        `divergence`, which even the OLD code already caught, because
        `is-ancestor(sha, divergence)` is true for a commit and itself. That
        left the actual reported bug unexercised: on a `pull_request` event,
        `actions/checkout@v4` checks out the MERGE ref, so verdict.json on
        disk can carry a sha main advanced to AFTER this branch's own
        divergence point -- a commit that is neither an ancestor of
        `divergence` (it comes after it) nor reachable from this branch's own
        `head` (this branch never merged it). The old code's `if ancestor:`
        alone is False here, and execution fell through to the generic
        "reviewed, then diverged" message on a branch that was never
        reviewed at all -- issue #14's own reported symptom.
        """
        divergence = _commit(self.repo, "main at the point feature is cut")
        _git(["checkout", "-q", "-b", "feature"], self.repo)
        _write(self.repo, "b.txt", "feature's own new work, never reviewed")
        head = _commit(self.repo, "feature's own first commit")
        _git(["checkout", "-q", "main"], self.repo)
        later_main = _commit(self.repo, "main moves on after feature was cut")
        _git(["checkout", "-q", "feature"], self.repo)
        # Simulates the merge-ref checkout: verdict.json on the PR's working
        # tree names a commit main advanced to, not anything from feature's
        # own history and not the original divergence point either.
        _write_verdict(self.repo, later_main)
        code, msg = check(self.repo, head)
        self.assertEqual(code, 1)
        self.assertIn("This branch has never been reviewed", msg)
        self.assertIn("predates this branch's own commits", msg)
        self.assertNotIn("The review does not cover this code", msg)

    def test_indeterminate_when_reachability_from_head_cannot_be_computed(self):
        """`_is_ancestor(sha, want)` -- the NEW git call this fix adds --
        must be given its own indeterminate path, distinct from the
        pre-existing divergence-point-unresolvable case.

        A sha that is merely invalid won't isolate this: `git diff
        sha..want` fails FIRST on such a sha, so control never reaches this
        fix's new code at all (that's `test_sha_unreachable_from_head_blocks`,
        above). To reach `_is_ancestor(sha, want)` specifically, the diff and
        the divergence merge-base must both succeed -- so `sha` is a real,
        valid, reachable commit -- and only the ONE new subprocess call this
        fix adds is made to fail, via a real subprocess.run wrapped to
        selectively raise for exactly that argv.
        """
        divergence = _commit(self.repo, "main at the point feature is cut")
        _git(["checkout", "-q", "-b", "feature"], self.repo)
        _write(self.repo, "b.txt", "feature's own new work")
        head = _commit(self.repo, "feature's own commit")
        # The verdict sha IS `divergence` -- deliberately, so both `git diff`
        # and the divergence `merge-base` succeed normally on it, and so the
        # mock below's exact-match filter has one unambiguous commit to
        # target. (An earlier draft of this fixture claimed the sha was
        # "not head or divergence", which was never true here and was
        # corrected by an independent review-tests pass, 2026-09-06 --
        # a reader trusting the old comment and swapping in some other sha
        # would have silently broken the mock's cmd[3:5] match below.)
        _write_verdict(self.repo, divergence)
        _commit(self.repo, "record a verdict for an older commit, then diverge")
        head = _git(["rev-parse", "HEAD"], self.repo).stdout.strip()

        real_run = subprocess.run

        def selective_failure(cmd, *args, **kwargs):
            # Only the FIRST is-ancestor call check() makes -- reachable_from_head,
            # (sha=divergence, of=head) -- is targeted. check() returns as soon as
            # this comes back None, so the later (sha, divergence) call this same
            # helper makes for the "ancestor" check never runs; nothing else needs
            # a case here.
            if cmd[:3] == ["git", "merge-base", "--is-ancestor"] and cmd[3:5] == [divergence, head]:
                raise OSError("simulated: the reachable-from-head check fails")
            return real_run(cmd, *args, **kwargs)

        with mock.patch("scripts.verdict_gate.subprocess.run", side_effect=selective_failure):
            code, msg = check(self.repo, head)
        self.assertEqual(code, 1)
        self.assertIn(
            "could not determine whether the recorded verdict is "
            "part of this branch's own history", msg,
        )
        self.assertNotIn("has never been reviewed", msg)
        self.assertNotIn("The review does not cover this code", msg)

    def test_indeterminate_when_ancestor_of_divergence_cannot_be_computed(self):
        """The SECOND `_is_ancestor` call check() makes -- `ancestor =
        _is_ancestor(sha, divergence)` -- gets its own distinct message
        (found by an independent review-code pass, 2026-09-06: an earlier
        draft blamed the wrong git call here). Reaching this call requires
        `reachable_from_head` to succeed first, so a DIFFERENT sha is
        targeted than the previous test -- here `sha == divergence` again,
        but the mock fails the SECOND call (sha, divergence), not the first
        (sha, head), which succeeds normally.
        """
        divergence = _commit(self.repo, "main at the point feature is cut")
        _git(["checkout", "-q", "-b", "feature"], self.repo)
        _write(self.repo, "b.txt", "feature's own new work")
        _write_verdict(self.repo, divergence)
        _commit(self.repo, "record a verdict for an older commit, then diverge")
        head = _git(["rev-parse", "HEAD"], self.repo).stdout.strip()

        real_run = subprocess.run

        def selective_failure(cmd, *args, **kwargs):
            if cmd[:3] == ["git", "merge-base", "--is-ancestor"] and cmd[3:5] == [divergence, divergence]:
                raise OSError("simulated: the ancestor-of-divergence check fails")
            return real_run(cmd, *args, **kwargs)

        with mock.patch("scripts.verdict_gate.subprocess.run", side_effect=selective_failure):
            code, msg = check(self.repo, head)
        self.assertEqual(code, 1)
        self.assertIn(
            "could not determine whether the recorded verdict "
            "predates this branch", msg,
        )
        self.assertNotIn(
            "part of this branch's own history", msg,
        )  # the OTHER indeterminate message, not this one
        self.assertNotIn("has never been reviewed", msg)
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

    def test_open_messages_are_distinguishable_from_each_other(self):
        """Both OPEN paths return exit 0, but they are reached through
        different logic (an exact sha match vs. a verdict-file-only diff) and
        must not be conflated into one generic "OPEN" string -- a caller
        relying on the message to tell the two apart (or a future test) needs
        them to actually differ in substance, not just both start with OPEN.
        """
        exact = _commit(self.repo, "first")
        _write_verdict(self.repo, exact)
        _, exact_msg = check(self.repo, exact)

        reviewed = _commit(self.repo, "reviewed here")
        _write_verdict(self.repo, reviewed)
        verdict_only_head = _commit(self.repo, "record the verdict, nothing else")
        _, diff_msg = check(self.repo, verdict_only_head)

        self.assertTrue(exact_msg.startswith("OPEN"))
        self.assertTrue(diff_msg.startswith("OPEN"))
        self.assertIn("matches head", exact_msg)
        self.assertNotIn("matches head", diff_msg)
        self.assertIn("the only change since is the verdict file itself", diff_msg)
        self.assertNotIn("the only change since", exact_msg)

    def test_block_message_names_the_full_remediation(self):
        """block()'s remediation text is what a contributor actually reads
        when the gate fires -- an assertion only on the leading BLOCKED
        summary line would miss a regression that garbled or dropped the
        instructions themselves (audit 2026-08-05, M6: a prior version of
        this remediation named a script path that did not exist).
        """
        head = _commit(self.repo, "first")
        code, msg = check(self.repo, head)  # no verdict.json at all
        self.assertEqual(code, 1)
        self.assertIn("This branch has no review recorded for its current state.", msg)
        self.assertIn("Run the review-final skill (serina:review-final).", msg)
        self.assertIn("verdict.sh record ready", msg)
        self.assertIn("Commit .superpowers/verdict.json and push.", msg)
        self.assertIn("verdict.sh ships with the skill, not with this repo.", msg)

    def test_resolves_origin_main_over_bare_main_when_both_exist(self):
        """_resolve_main_ref tries "origin/main" before bare "main". A real
        `origin` remote (a second bare repo, actually fetched) exercises that
        first branch -- every other fixture in this file has no remote at
        all, so falls through to testing only the second, fallback path.

        CORRECTED (found by an independent review-tests pass, 2026-09-06):
        an earlier draft of this fixture wrote the verdict for `main_tip`,
        the commit pushed AS origin/main -- but `main_tip` is also an
        ancestor of local main's later tip, so `ancestor(main_tip, X)` is
        True for EITHER candidate divergence point, and the test passed
        the same way even with `_resolve_main_ref` edited to try only
        `("main",)`, never touching origin/main at all. To actually
        discriminate, the verdict sha must be an ancestor of ONE candidate
        ref's divergence point but not the other -- `local_only`, the
        commit that advances local main PAST what was pushed to origin,
        does that: it is not an ancestor of origin/main's (older) tip, but
        it IS an ancestor of (in fact equal to) local main's tip.
        """
        with tempfile.TemporaryDirectory() as remote:
            _git(["init", "-q", "--bare", "-b", "main"], remote)
            _git(["remote", "add", "origin", remote], self.repo)
            _commit(self.repo, "the shared root, pushed to origin")
            _git(["push", "-q", "origin", "main"], self.repo)
            # Advances local main PAST what origin/main has -- never pushed.
            local_only = _commit(self.repo, "local main moves on, never pushed")
            _git(["checkout", "-q", "-b", "feature"], self.repo)
            _write(self.repo, "b.txt", "feature's own new work")
            head = _commit(self.repo, "feature's own first commit")
            _write_verdict(self.repo, local_only)
            _commit(self.repo, "record a verdict, then diverge")
            head = _git(["rev-parse", "HEAD"], self.repo).stdout.strip()
            code, msg = check(self.repo, head)
        # If origin/main were skipped (bug: falls back straight to bare
        # "main"), divergence would resolve to `local_only` itself, sha
        # would be its own ancestor, and this would wrongly read as
        # "never reviewed" instead.
        self.assertEqual(code, 1)
        self.assertIn("file(s) changed since", msg)
        self.assertIn("The review does not cover this code", msg)
        self.assertNotIn("has never been reviewed", msg)


class VerdictGateMainCliTests(unittest.TestCase):
    """main() end-to-end, as a real subprocess -- covering argv parsing,
    HEAD_SHA env-var reading, and the exit code actually returned to the
    shell, none of which check()'s own unit tests exercise.
    """

    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.repo = self._td.name
        _init_repo(self.repo)
        self._script = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "scripts", "verdict_gate.py",
        )

    def tearDown(self):
        self._td.cleanup()

    def _run_main(self, head_sha, cwd=None):
        env = dict(os.environ, HEAD_SHA=head_sha)
        return subprocess.run(
            [sys.executable, self._script, self.repo],
            env=env, cwd=cwd, capture_output=True, text=True, timeout=30,
        )

    def test_main_exits_zero_and_prints_open_when_ready(self):
        head = _commit(self.repo, "first")
        _write_verdict(self.repo, head)
        result = self._run_main(head)
        self.assertEqual(result.returncode, 0)
        self.assertTrue(result.stdout.startswith("OPEN"))

    def test_main_actually_uses_the_argv_repo_root_not_its_own_cwd(self):
        """CORRECTED (found by an independent review-tests pass, 2026-09-06):
        the original test_main_exits_one_and_prints_blocked_when_absent
        passed even with `main()` hardcoded to ignore argv[1] entirely and
        always use "." -- because whatever directory a test happens to run
        from also lacks a matching verdict for a synthetic head sha, so
        BLOCKED came back for the wrong reason either way.

        This pins it properly: run the subprocess from a DIFFERENT cwd (a
        second real repo carrying a verdict for the SAME head sha, which
        would read OPEN if `main()` mistakenly used its own cwd) while
        passing self.repo -- which carries no verdict at all -- as the
        explicit argv[1]. Only reading argv[1] correctly can produce this
        exact BLOCKED/absent outcome; reading cwd instead would produce OPEN.
        """
        head = _commit(self.repo, "first")
        with tempfile.TemporaryDirectory() as decoy:
            _init_repo(decoy)
            _commit(decoy, "unrelated decoy repo")
            _write_verdict(decoy, head, state="READY")  # sha == want by construction below
            result = self._run_main(head, cwd=decoy)
        self.assertEqual(result.returncode, 1)
        self.assertTrue(result.stdout.startswith("BLOCKED"))
        self.assertIn(f"no {VERDICT_PATH} in this branch.", result.stdout)

    def test_main_exits_one_and_prints_blocked_when_absent(self):
        head = _commit(self.repo, "first")
        result = self._run_main(head)
        self.assertEqual(result.returncode, 1)
        self.assertTrue(result.stdout.startswith("BLOCKED"))


if __name__ == "__main__":
    unittest.main()
