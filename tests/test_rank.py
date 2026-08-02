import unittest
from loom.rank import needs_you


def repo(**over):
    base = {"worktrees": [], "prs": [], "collisions": [], "flags": []}
    base.update(over)
    return base


def tree(dir_, branch, state="none", unstaged=0):
    return {"dir": dir_, "branch": branch,
            "agent": {"state": state, "source": "hook"},
            "dirty": {"staged": 0, "unstaged": unstaged, "untracked": 0}}


def pr(number, branch, review=None, checks="none"):
    return {"number": number, "branch": branch, "review": review,
            "checks": checks, "draft": False}


class TestNeedsYou(unittest.TestCase):
    def test_a_quiet_fleet_produces_an_empty_strip(self):
        # Negative control: the strip must be able to be empty.
        self.assertEqual(needs_you(repo(worktrees=[tree("a", "feature-a", "working")])), [])

    def test_a_waiting_agent_ranks_first(self):
        items = needs_you(repo(
            worktrees=[tree("a", "feature-a", "waiting")],
            prs=[pr(1, "feature-a")],
        ))
        self.assertEqual(items[0]["rank"], 1)
        self.assertEqual(items[0]["kind"], "agent_waiting")

    def test_a_reviewless_pr_with_no_ci_still_ranks(self):
        # The spec said "checks pass". No CI is configured on the reference repo,
        # so requiring "passing" would make this rank unreachable.
        items = needs_you(repo(prs=[pr(58, "x", review=None, checks="none")]))
        self.assertEqual([i["kind"] for i in items], ["pr_awaiting_review"])

    def test_a_failing_pr_does_not_count_as_awaiting_review(self):
        items = needs_you(repo(prs=[pr(58, "x", review=None, checks="failing")]))
        self.assertEqual([i["kind"] for i in items], ["pr_failing"])

    def test_an_approved_pr_is_not_awaiting_review(self):
        self.assertEqual(needs_you(repo(prs=[pr(58, "x", review="APPROVED")])), [])

    def test_a_draft_pr_is_not_awaiting_review(self):
        d = pr(58, "x")
        d["draft"] = True
        self.assertEqual(needs_you(repo(prs=[d])), [])

    def test_a_collision_ranks_third(self):
        items = needs_you(repo(collisions=[{"file": "src/a.ts", "branches": ["one", "two"]}]))
        self.assertEqual((items[0]["rank"], items[0]["kind"]), (3, "collision"))

    def test_a_stopped_agent_with_dirt_ranks_fifth(self):
        items = needs_you(repo(worktrees=[tree("a", "fa", "stopped", unstaged=4)]))
        self.assertEqual((items[0]["rank"], items[0]["kind"]), (5, "stopped_dirty"))

    def test_a_stopped_agent_with_a_clean_tree_is_quiet(self):
        self.assertEqual(needs_you(repo(worktrees=[tree("a", "fa", "stopped")])), [])

    def test_items_come_back_in_rank_order(self):
        items = needs_you(repo(
            worktrees=[tree("a", "fa", "waiting")],
            collisions=[{"file": "src/a.ts", "branches": ["one", "two"]}],
            flags=[{"kind": "stale_dir", "severity": "warn", "subject": "old", "detail": "d"}],
        ))
        self.assertEqual([i["rank"] for i in items], sorted(i["rank"] for i in items))
        self.assertEqual(items[0]["rank"], 1)


if __name__ == "__main__":
    unittest.main()
