import json
import unittest
from loom.runner import ReplayRunner
from loom.ghsrc import origin_repo, fetch_prs, fetch_issues, derive_checks

PR_ARGS = ("gh pr list -R you/example --state open --limit 50 --json "
           "number,title,headRefName,isDraft,reviewDecision,statusCheckRollup,updatedAt")
ISSUE_ARGS = ("gh issue list -R you/example --state open --limit 50 --json "
              "number,title,labels,assignees")


class TestOriginRepo(unittest.TestCase):
    def _repo(self, url):
        runner = ReplayRunner({
            "git remote get-url origin": {"returncode": 0, "stdout": url + "\n", "stderr": ""},
        })
        return origin_repo(runner, "/repo")

    def test_parses_ssh_form(self):
        self.assertEqual(self._repo("git@github.com:you/example.git"), "you/example")

    def test_parses_https_form(self):
        self.assertEqual(self._repo("https://github.com/you/example.git"), "you/example")

    def test_parses_https_without_dot_git(self):
        self.assertEqual(self._repo("https://github.com/you/example"), "you/example")

    def test_unrecognised_remote_is_none_not_a_guess(self):
        self.assertIsNone(self._repo("ssh://someone@gitlab.internal/x/y.git"))


class TestDeriveChecks(unittest.TestCase):
    def test_no_checks_configured_is_none_not_passing(self):
        self.assertEqual(derive_checks([]), "none")

    def test_any_failure_is_failing(self):
        self.assertEqual(derive_checks([
            {"status": "COMPLETED", "conclusion": "SUCCESS"},
            {"status": "COMPLETED", "conclusion": "FAILURE"},
        ]), "failing")

    def test_incomplete_is_pending(self):
        self.assertEqual(derive_checks([{"status": "IN_PROGRESS", "conclusion": None}]), "pending")

    def test_all_successful_is_passing(self):
        self.assertEqual(derive_checks([{"status": "COMPLETED", "conclusion": "SUCCESS"}]), "passing")

    def test_legacy_commit_status_pending_is_pending(self):
        # Legacy commit-status contexts have state but no status key
        self.assertEqual(derive_checks([{"state": "PENDING", "context": "ci/x"}]), "pending")

    def test_legacy_commit_status_expected_is_pending(self):
        # Unknown legacy states should degrade to pending, not pass
        self.assertEqual(derive_checks([{"state": "EXPECTED", "context": "ci/x"}]), "pending")

    def test_check_run_stale_is_pending(self):
        # Unknown conclusion states should degrade to pending
        self.assertEqual(derive_checks([{"status": "COMPLETED", "conclusion": "STALE"}]), "pending")

    def test_invented_future_state_is_pending(self):
        # New states not in the whitelist must not report as passing
        self.assertEqual(derive_checks([{"status": "COMPLETED", "conclusion": "SOME_FUTURE_STATE"}]), "pending")

    def test_skipped_is_passing(self):
        # SKIPPED is in the whitelist and should pass
        self.assertEqual(derive_checks([{"status": "COMPLETED", "conclusion": "SKIPPED"}]), "passing")


class TestFetchPrs(unittest.TestCase):
    def test_empty_review_decision_becomes_none(self):
        payload = json.dumps([{
            "number": 67, "title": "One owner for the clues",
            "headRefName": "fix/one-clues-owner", "isDraft": False,
            "reviewDecision": "", "statusCheckRollup": [],
            "updatedAt": "2026-08-02T20:49:00Z",
        }])
        runner = ReplayRunner({PR_ARGS: {"returncode": 0, "stdout": payload, "stderr": ""}})
        prs, status = fetch_prs(runner, "/repo", "you/example")
        self.assertIsNone(prs[0].review)
        self.assertEqual(prs[0].checks, "none")
        self.assertTrue(status.ok)

    def test_the_repo_is_always_pinned_with_dash_R(self):
        runner = ReplayRunner({PR_ARGS: {"returncode": 0, "stdout": "[]", "stderr": ""}})
        fetch_prs(runner, "/repo", "you/example")
        self.assertIn("-R", runner.calls[0])
        self.assertIn("you/example", runner.calls[0])

    def test_failure_is_reported_not_swallowed_as_empty(self):
        runner = ReplayRunner({
            PR_ARGS: {"returncode": 1, "stdout": "", "stderr": "HTTP 403: rate limited\n"},
        })
        prs, status = fetch_prs(runner, "/repo", "you/example")
        self.assertEqual(prs, [])
        self.assertFalse(status.ok)
        self.assertIn("403", status.error)

    def test_genuinely_empty_is_a_success_not_a_failure(self):
        # The distinction this whole design exists to preserve.
        runner = ReplayRunner({PR_ARGS: {"returncode": 0, "stdout": "[]", "stderr": ""}})
        prs, status = fetch_prs(runner, "/repo", "you/example")
        self.assertEqual(prs, [])
        self.assertTrue(status.ok)
        self.assertIsNone(status.error)

    def test_a_malformed_record_is_skipped_and_degrades_the_source_not_the_snapshot(self):
        # One bad record from a future `gh` schema/version change must not crash
        # collect() entirely, and the good record next to it must not be dropped
        # silently under a still-green status.
        payload = json.dumps([
            {"number": 67, "title": "Good one", "headRefName": "fix/x", "isDraft": False,
             "reviewDecision": "", "statusCheckRollup": [], "updatedAt": "2026-08-02T20:49:00Z"},
            {"title": "Missing its number", "headRefName": "fix/y"},
        ])
        runner = ReplayRunner({PR_ARGS: {"returncode": 0, "stdout": payload, "stderr": ""}})
        prs, status = fetch_prs(runner, "/repo", "you/example")
        self.assertEqual([p.number for p in prs], [67])
        self.assertFalse(status.ok)
        self.assertIsNotNone(status.error)


class TestFetchIssues(unittest.TestCase):
    def test_labels_are_flattened_to_names(self):
        payload = json.dumps([{
            "number": 55, "title": "A retried clue read",
            "labels": [{"name": "bug"}, {"name": "client"}], "assignees": [],
        }])
        runner = ReplayRunner({ISSUE_ARGS: {"returncode": 0, "stdout": payload, "stderr": ""}})
        issues, status = fetch_issues(runner, "/repo", "you/example")
        self.assertEqual(issues[0].labels, ["bug", "client"])

    def test_a_malformed_record_is_skipped_and_degrades_the_source_not_the_snapshot(self):
        payload = json.dumps([
            {"number": 55, "title": "Good one", "labels": [], "assignees": []},
            {"number": 56, "title": "Bad label", "labels": [{"not_name": "x"}], "assignees": []},
        ])
        runner = ReplayRunner({ISSUE_ARGS: {"returncode": 0, "stdout": payload, "stderr": ""}})
        issues, status = fetch_issues(runner, "/repo", "you/example")
        self.assertEqual([i.number for i in issues], [55])
        self.assertFalse(status.ok)
        self.assertIsNotNone(status.error)


if __name__ == "__main__":
    unittest.main()
