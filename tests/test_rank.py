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

    # ------------------------------------------------- audit 2026-08-05, H2
    # `reviewDecision` is a FOUR-VALUED ENUM, and rank 2 tested it for
    # truthiness. `REVIEW_REQUIRED` -- the exact state rank 2 exists to catch --
    # is a truthy string, so it read as "already reviewed" and rank 2 fired only
    # on `null`, i.e. only on repos with NO review requirement at all. On any
    # repo configured the way this one is, the second-most-important alert in the
    # product was unreachable.
    #
    # One test per value, so no value can regress unobserved again.

    def test_a_review_required_pr_ranks_as_awaiting_review(self):
        # THE REGRESSION GUARD. gh reports reviewDecision="REVIEW_REQUIRED" on
        # any repo with required reviews -- including this one.
        items = needs_you(repo(prs=[pr(58, "x", review="REVIEW_REQUIRED")]))
        self.assertEqual([i["kind"] for i in items], ["pr_awaiting_review"])

    def test_a_review_required_pr_with_failing_checks_ranks_as_failing_not_awaiting(self):
        # Rank 4 still wins over rank 2: the spec's rank 2 is "no review, and
        # checks NOT failing".
        items = needs_you(repo(prs=[pr(58, "x", review="REVIEW_REQUIRED",
                                       checks="failing")]))
        self.assertEqual([i["kind"] for i in items], ["pr_failing"])

    def test_a_changes_requested_pr_is_not_awaiting_review(self):
        # Deliberately NOT rank 2. `CHANGES_REQUESTED` is blocked on the AUTHOR,
        # and rank 2's stated rationale is "only a human moves it". An agent can
        # act on requested changes, so promoting it here would dilute the alert.
        #
        # It is also invisible at every other rank, which is a real gap -- but
        # closing it means adding a rank to the spec's ranking table, a design
        # decision rather than a bug fix. Recorded in the remediation log instead
        # of decided here.
        self.assertEqual(
            needs_you(repo(prs=[pr(58, "x", review="CHANGES_REQUESTED")])), [])

    def test_a_draft_pr_is_exempt_even_when_a_review_is_required(self):
        d = pr(58, "x", review="REVIEW_REQUIRED")
        d["draft"] = True
        self.assertEqual(needs_you(repo(prs=[d])), [])

    def test_an_unrecognised_review_decision_does_not_rank(self):
        # A value GitHub has not invented yet must not be guessed into an alert.
        # Silence is the safe direction: a false rank 2 cries wolf on the strip.
        self.assertEqual(
            needs_you(repo(prs=[pr(58, "x", review="SOME_FUTURE_STATE")])), [])

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

    # ------------------------------------------------- audit 2026-08-05, H3
    def test_a_stopped_agent_with_an_unmeasurable_tree_is_flagged_not_silenced(self):
        """`dirty: None` means CANNOT TELL, and rank 5 guards work at risk.

        Before H3, a failed `git status` returned Dirty(0,0,0), so a stopped agent
        whose tree could not be measured was indistinguishable from one that had
        committed everything -- and rank 5, whose whole rationale is "work at risk
        of being lost", was silently suppressed exactly when it mattered.

        Silence is NOT the safe direction here. Every other guard in this codebase
        stays quiet when it cannot tell, because a false alarm cries wolf. Rank 5
        is the opposite: the cost of a false alarm is one glance, and the cost of a
        false silence is lost work. So an unmeasurable tree with a stopped agent
        raises rank 5 and says plainly that it could not be measured.
        """
        t = tree("a", "fa", "stopped")
        t["dirty"] = None
        items = needs_you(repo(worktrees=[t]))
        self.assertEqual([(i["rank"], i["kind"]) for i in items],
                         [(5, "stopped_dirty")])
        self.assertIn("could not", items[0]["detail"].lower())

    def test_a_working_agent_with_an_unmeasurable_tree_does_not_rank(self):
        # Negative control: rank 5 is about STOPPED or STALE agents. An
        # unmeasurable tree under a live agent is not work at risk.
        t = tree("a", "fa", "working")
        t["dirty"] = None
        self.assertEqual(needs_you(repo(worktrees=[t])), [])

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




class TestRankAgainstRealAgentFor(unittest.TestCase):
    """The original reproduction from PR #12's review, driven end to end.

    Every other rank test injects `age_seconds` through the `tree()` helper, which
    bypasses `agent_for`'s merge entirely. So the two-session scenario that
    actually motivated the fix — a crashed `waiting` record beside a live
    `working` one — was verified by hand and pinned by nothing. A regression in
    how `agent_for` picks the winner, or in whether it populates `age_seconds` at
    all, would have been invisible to the suite.
    """

    def _tree_from(self, sessions, now):
        from dataclasses import asdict
        from loom.agents import agent_for
        a = agent_for("/repo", sessions, [], now)
        return {"dir": "repo", "branch": "main", "agent": asdict(a),
                "dirty": {"staged": 0, "unstaged": 0, "untracked": 0}}

    def test_a_crashed_waiting_record_does_not_mask_a_live_working_one(self):
        from datetime import datetime, timedelta, timezone
        from loom.rank import RANK1_MAX_AGE_SECONDS
        now = datetime(2026, 8, 4, 12, 0, 0, tzinfo=timezone.utc)
        ago = lambda s: (now - timedelta(seconds=s)).isoformat()
        sessions = [
            # closed at a permission prompt, well past the rank-1 window
            {"cwd": "/repo", "state": "waiting", "pid": 999,
             "since": ago(RANK1_MAX_AGE_SECONDS * 4)},
            # demonstrably alive
            {"cwd": "/repo", "state": "working", "pid": 123, "since": ago(3)},
        ]
        tree = self._tree_from(sessions, now)
        # The row still reports `waiting` — that is deliberate, since a blocked
        # agent may genuinely be there and hiding it would be the unsafe direction.
        self.assertEqual(tree["agent"]["state"], "waiting")
        # But it must NOT claim the top alert on a claim it cannot date as recent.
        self.assertEqual([i["kind"] for i in needs_you(repo(worktrees=[tree]))], [])

    def test_a_genuinely_fresh_waiting_record_still_reaches_rank_1(self):
        # The positive control: without it the test above could pass because
        # agent_for never populates age_seconds at all.
        from datetime import datetime, timedelta, timezone
        now = datetime(2026, 8, 4, 12, 0, 0, tzinfo=timezone.utc)
        sessions = [{"cwd": "/repo", "state": "waiting", "pid": 1,
                     "since": (now - timedelta(seconds=30)).isoformat()}]
        tree = self._tree_from(sessions, now)
        self.assertIsNotNone(tree["agent"]["age_seconds"],
                             "agent_for must populate age_seconds or rank 1 can never fire")
        self.assertEqual([i["kind"] for i in needs_you(repo(worktrees=[tree]))],
                         ["agent_waiting"])


if __name__ == "__main__":
    unittest.main()
