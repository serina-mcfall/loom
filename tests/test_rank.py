import unittest
from loom.rank import needs_you


def repo(**over):
    base = {"worktrees": [], "prs": [], "collisions": [], "flags": []}
    base.update(over)
    return base


def tree(dir_, branch, state="none", unstaged=0, age=5.0):
    # `age` defaults to 5 seconds — freshly refreshed — because that is what an
    # existing fixture written before rank 1 required freshness meant to say.
    # Tests about staleness state it explicitly.
    return {"dir": dir_, "branch": branch,
            "agent": {"state": state, "source": "hook", "age_seconds": age},
            "dirty": {"staged": 0, "unstaged": unstaged, "untracked": 0}}


def pr(number, branch, review=None, checks="none"):
    return {"number": number, "branch": branch, "review": review,
            "checks": checks, "draft": False}


class TestNeedsYou(unittest.TestCase):
    def test_a_stale_waiting_claim_does_not_earn_rank_1(self):
        # THE REGRESSION GUARD. A terminal closed at a permission prompt leaves a
        # `waiting` record that never refreshes, and nothing else clears it —
        # reap() only removes `stopped`. Before this, rank 1 stayed lit for twelve
        # hours, and a strip that is never empty is a strip nobody reads.
        from loom.rank import RANK1_MAX_AGE_SECONDS
        r = repo(worktrees=[tree("a", "fa", "waiting", age=RANK1_MAX_AGE_SECONDS + 60)])
        self.assertEqual([i["kind"] for i in needs_you(r)], [])

    def test_a_fresh_waiting_claim_still_earns_rank_1(self):
        # The positive control. Without it the guard above could pass simply
        # because rank 1 never fires at all.
        from loom.rank import RANK1_MAX_AGE_SECONDS
        r = repo(worktrees=[tree("a", "fa", "waiting", age=RANK1_MAX_AGE_SECONDS - 60)])
        self.assertEqual([i["kind"] for i in needs_you(r)], ["agent_waiting"])

    def test_an_undatable_waiting_claim_does_not_earn_rank_1(self):
        # age_seconds is None when the timestamp is missing, unreadable, naive or
        # in the future. "I cannot date this" must not be promoted to the top
        # alert — but the worktree row still shows `waiting`, so nothing is hidden.
        r = repo(worktrees=[tree("a", "fa", "waiting", age=None)])
        self.assertEqual([i["kind"] for i in needs_you(r)], [])

    def test_a_waiting_claim_with_no_age_field_at_all_does_not_earn_rank_1(self):
        # An older snapshot, or a hand-written one, has no age_seconds key. Absent
        # must behave as undatable rather than as fresh.
        r = repo(worktrees=[{"dir": "a", "branch": "fa",
                             "agent": {"state": "waiting", "source": "hook"},
                             "dirty": {"staged": 0, "unstaged": 0, "untracked": 0}}])
        self.assertEqual([i["kind"] for i in needs_you(r)], [])

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

    def test_draft_pr_with_failing_checks_is_silent(self):
        # A draft is exempt from both rank 2 (awaiting review) and rank 4 (failing checks).
        # Failing checks in a draft are expected (work in progress), so ranking them
        # would create noise and train users to ignore the strip.
        d = pr(10, "feature", checks="failing")
        d["draft"] = True
        self.assertEqual(needs_you(repo(prs=[d])), [])

    def test_pr_numbers_sort_numerically_not_lexicographically(self):
        # PR #9 should come before #10, not PR #10 before #9 (which is lexicographic order).
        items = needs_you(repo(prs=[
            pr(10, "x", review=None),
            pr(9, "x", review=None),
            pr(11, "x", review=None),
        ]))
        subjects = [i["subject"] for i in items]
        self.assertEqual(subjects, ["PR #9", "PR #10", "PR #11"])

    def test_missing_worktree_dir_does_not_raise(self):
        # If a worktree dict is missing "dir", the entry should use a placeholder,
        # not raise KeyError and lose the entire strip.
        items = needs_you(repo(worktrees=[
            {"agent": {"state": "waiting", "source": "hook", "age_seconds": 5.0}, "branch": "x",
             "dirty": {"staged": 0, "unstaged": 0, "untracked": 0}},
        ]))
        self.assertEqual(items[0]["subject"], "<unnamed worktree>")

    def test_missing_pr_number_does_not_raise(self):
        # If a PR dict is missing "number", the entry should use a placeholder,
        # not raise KeyError and lose the entire strip.
        items = needs_you(repo(prs=[
            {"branch": "x", "review": None, "checks": "none", "draft": False},
        ]))
        self.assertEqual(items[0]["subject"], "PR #?")

    def test_collision_with_single_branch_is_silent(self):
        # A collision requires at least two branches; one branch is not a collision.
        items = needs_you(repo(collisions=[
            {"file": "src/a.ts", "branches": ["one"]},
        ]))
        self.assertEqual(items, [])

    def test_missing_collision_file_does_not_raise(self):
        # If a collision dict is missing "file", the entry should use a placeholder.
        items = needs_you(repo(collisions=[
            {"branches": ["one", "two"]},
        ]))
        self.assertEqual(items[0]["subject"], "<unknown file>")

    def test_multiple_items_at_different_ranks_all_appear(self):
        # A fixture creating entries at two different ranks should return both.
        items = needs_you(repo(
            worktrees=[tree("a", "feature", "waiting")],
            prs=[pr(1, "feature", review=None)],
        ))
        self.assertEqual(len(items), 2)
        self.assertEqual(items[0]["rank"], 1)
        self.assertEqual(items[1]["rank"], 2)

    def test_quiet_fleet_remains_empty(self):
        # Negative control: a healthy fleet with working agents produces an empty strip.
        # This is the most important test in the file.
        result = needs_you(repo(
            worktrees=[tree("a", "feature-a", "working")],
            prs=[pr(1, "feature-a", review="APPROVED")],
        ))
        self.assertEqual(result, [])


if __name__ == "__main__":
    unittest.main()
