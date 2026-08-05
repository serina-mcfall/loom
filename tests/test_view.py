"""Audit 2026-08-05, findings H6 and H8.

`loom.js` held 148 lines of rendering logic with no test of any kind, and two
confirmed defects lived in it. The chosen remedy (H8) is to move the DECISIONS --
what to display -- into pure Python that the contract tests can exercise, leaving
`loom.js` as plumbing that renders what it is handed.

The decision these tests pin hardest is H6's: the page showed a green "live" badge
whenever an SSE message arrived, and a message arrives *because* collection
failed -- `_refresh_step` adds `refresh_error` to the previous snapshot, which
changes the serialised body, which triggers a send. So the one condition under
which the dashboard was lying is the condition under which it most confidently
claimed to be live.
"""
from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from loom.view import STALE_AFTER_SECONDS, badge, finalise


def iso(delta_seconds: float = 0.0) -> str:
    when = datetime.now(timezone.utc).astimezone() + timedelta(seconds=delta_seconds)
    return when.isoformat(timespec="seconds")


class TestBadge(unittest.TestCase):
    def test_before_the_first_collection_it_is_connecting_not_live(self):
        b = badge({"schema": 1, "repos": [], "collected": False})
        self.assertEqual(b["state"], "connecting")

    def test_a_fresh_snapshot_is_live(self):
        b = badge({"collected": True, "generated_at": iso(), "refresh_error": None})
        self.assertEqual(b["state"], "live")

    def test_a_refresh_error_is_an_error_however_fresh_the_stamp(self):
        """THE H6 REGRESSION GUARD.

        `_refresh_step` returns the PREVIOUS snapshot with `refresh_error` set and
        `generated_at` deliberately left unchanged. A freshly-stamped snapshot
        carrying an error must still read as an error -- and the error must win
        over every other signal, because it is the only one that says the data is
        not merely old but actively not being collected.
        """
        b = badge({"collected": True, "generated_at": iso(),
                   "refresh_error": "KeyError: 'prs'"})
        self.assertEqual(b["state"], "error")
        self.assertIn("KeyError", b["detail"])

    def test_an_old_snapshot_is_stale_even_with_no_error(self):
        b = badge({"collected": True, "generated_at": iso(-STALE_AFTER_SECONDS - 5),
                   "refresh_error": None})
        self.assertEqual(b["state"], "stale")

    def test_a_snapshot_just_inside_the_window_is_still_live(self):
        b = badge({"collected": True, "generated_at": iso(-1), "refresh_error": None})
        self.assertEqual(b["state"], "live")

    def test_a_missing_timestamp_is_not_reported_live(self):
        # Cannot tell how old it is, so it must not claim freshness. Silence in the
        # reassuring direction is the failure mode this whole project refuses.
        b = badge({"collected": True, "refresh_error": None})
        self.assertNotEqual(b["state"], "live")

    def test_a_naive_timestamp_is_not_reported_live(self):
        # A stamp with no offset gives a zone-dependent age -- the exact trap
        # loom/agents.py's `_age_seconds` refuses for hook records.
        b = badge({"collected": True, "generated_at": "2026-08-05T12:00:00",
                   "refresh_error": None})
        self.assertNotEqual(b["state"], "live")

    def test_an_unparseable_timestamp_is_not_reported_live(self):
        b = badge({"collected": True, "generated_at": "not a timestamp",
                   "refresh_error": None})
        self.assertNotEqual(b["state"], "live")

    def test_a_future_timestamp_is_not_reported_live(self):
        # Evidence of a broken producer, not of health -- same rule as _age_seconds.
        b = badge({"collected": True, "generated_at": iso(3600), "refresh_error": None})
        self.assertNotEqual(b["state"], "live")

    def test_every_state_carries_the_staleness_threshold_for_the_page(self):
        """Audit 2026-08-05, M10's other half.

        `/events` no longer suppresses identical frames, so frames ARE the heartbeat:
        silence means the server stopped collecting. The page needs the same
        threshold to notice that silence, and hardcoding it in loom.js would be a
        second copy of a policy that belongs here.
        """
        for snap in ({"collected": False},
                     {"collected": True, "generated_at": iso()},
                     {"collected": True, "generated_at": iso(), "refresh_error": "x"}):
            with self.subTest(snap=snap):
                self.assertEqual(badge(snap)["stale_after_seconds"],
                                 STALE_AFTER_SECONDS)

    def test_every_state_carries_a_label_a_glyph_and_a_word(self):
        """Colour is never the only carrier of meaning.

        The spec makes this a requirement rather than an aspiration, and it is the
        reason these labels live here where they can be asserted, instead of in a
        JS lookup table nothing tests.
        """
        cases = [
            {"collected": False},
            {"collected": True, "generated_at": iso()},
            {"collected": True, "generated_at": iso(-STALE_AFTER_SECONDS - 5)},
            {"collected": True, "generated_at": iso(), "refresh_error": "boom"},
        ]
        for snap in cases:
            b = badge(snap)
            with self.subTest(state=b["state"]):
                self.assertTrue(b["label"].strip(), "no label")
                # A word, not just a glyph: at least three letters of real text.
                letters = [c for c in b["label"] if c.isalpha()]
                self.assertGreaterEqual(len(letters), 3, f"glyph only: {b['label']!r}")


class TestAggregateNeeds(unittest.TestCase):
    """Audit 2026-08-05, finding H5.

    `serve --all` collected every repo under ~/Launchpad -- 12 subprocess spawns
    each, every 2 seconds -- and the page rendered `snapshot.repos[0]`, silently
    discarding the rest. `--all` is documented for `serve` in both the README and
    the CLI usage string.

    The strip stays ONE aggregated live region across every repo, rather than one
    region per repo: N polite live regions announcing independently is how a
    screen reader becomes unusable, which is the same reasoning that debounced the
    strip to 15 seconds in the first place.
    """

    def _snap(self, *repos: dict) -> dict:
        return {"schema": 1, "collected": True, "repos": list(repos)}

    def _repo(self, name: str, **over) -> dict:
        base = {"name": name, "worktrees": [], "prs": [], "collisions": [],
                "flags": [], "issues": [], "sources": []}
        base.update(over)
        return base

    def _failing_pr(self, number: int) -> dict:
        return {"number": number, "branch": f"b{number}", "draft": False,
                "review": None, "checks": "failing"}

    def test_a_single_repo_label_is_just_the_subject(self):
        from loom.view import aggregate_needs
        snap = finalise(self._snap(self._repo("one", prs=[self._failing_pr(7)])))
        items = aggregate_needs(snap)
        self.assertEqual([i["label"] for i in items], ["PR #7"])

    def test_several_repos_disambiguate_the_subject_by_repo(self):
        from loom.view import aggregate_needs
        snap = finalise(self._snap(
            self._repo("one", prs=[self._failing_pr(7)]),
            self._repo("two", prs=[self._failing_pr(7)]),
        ))
        items = aggregate_needs(snap)
        # Both are "PR #7". Without the repo name the strip is ambiguous about
        # which fleet member needs attention -- and worse, looks duplicated.
        self.assertEqual([i["label"] for i in items], ["one · PR #7", "two · PR #7"])

    def test_every_repo_contributes_not_only_the_first(self):
        from loom.view import aggregate_needs
        snap = finalise(self._snap(
            self._repo("one"),
            self._repo("two", prs=[self._failing_pr(9)]),
        ))
        items = aggregate_needs(snap)
        self.assertEqual([i["repo"] for i in items], ["two"],
                         "a later repo's alert must not be discarded")

    def test_items_are_ordered_by_rank_across_repos(self):
        from loom.view import aggregate_needs
        rank4 = self._repo("aaa", prs=[self._failing_pr(1)])
        rank2 = self._repo("zzz", prs=[{"number": 2, "branch": "b", "draft": False,
                                        "review": None, "checks": "none"}])
        snap = finalise(self._snap(rank4, rank2))
        items = aggregate_needs(snap)
        # Rank must beat repo name: a rank 2 in the last repo outranks a rank 4 in
        # the first, or the strip stops being a triage order.
        self.assertEqual([i["rank"] for i in items], [2, 4])

    def test_show_repo_states_whether_the_page_should_print_the_repo_name(self):
        """The page must not have to infer this by comparing label to subject.

        Whether a repo name is worth the clutter is a DECISION, so it is decided
        here and asserted here, per finding H8. The page reads the flag.
        """
        from loom.view import aggregate_needs
        one = finalise(self._snap(self._repo("one", prs=[self._failing_pr(7)])))
        self.assertEqual([i["show_repo"] for i in aggregate_needs(one)], [False])

        two = finalise(self._snap(
            self._repo("one", prs=[self._failing_pr(7)]),
            self._repo("two", prs=[self._failing_pr(8)]),
        ))
        self.assertEqual([i["show_repo"] for i in aggregate_needs(two)], [True, True])

    def test_an_empty_fleet_aggregates_to_nothing(self):
        from loom.view import aggregate_needs
        snap = finalise(self._snap(self._repo("one"), self._repo("two")))
        self.assertEqual(aggregate_needs(snap), [])

    def test_finalise_attaches_the_aggregate_at_the_top_level(self):
        snap = finalise(self._snap(self._repo("one", prs=[self._failing_pr(7)])))
        self.assertEqual([i["label"] for i in snap["needs_you"]], ["PR #7"])
        # And the per-repo lists survive, since each repo panel still shows its own.
        self.assertEqual(len(snap["repos"][0]["needs_you"]), 1)


class TestFinalise(unittest.TestCase):
    """`finalise` is the single boundary both consumers call, so the CLI's JSON and
    the server's SSE frames cannot drift into different shapes -- which is exactly
    how H7 happened."""

    def _snap(self) -> dict:
        return {
            "schema": 1, "collected": True, "generated_at": iso(),
            "refresh_error": None,
            "repos": [{
                "name": "one", "worktrees": [], "collisions": [], "flags": [],
                "issues": [], "sources": [],
                "prs": [{"number": 7, "branch": "b", "draft": False,
                         "review": None, "checks": "failing"}],
            }],
        }

    def test_it_ranks_every_repo(self):
        snap = finalise(self._snap())
        self.assertEqual([i["kind"] for i in snap["repos"][0]["needs_you"]],
                         ["pr_failing"])

    def test_it_attaches_a_badge(self):
        self.assertIn("badge", finalise(self._snap()))

    def test_it_is_idempotent(self):
        # Called twice -- by a careless caller, or by both a builder and a server
        # -- it must not double-count anything.
        once = finalise(self._snap())
        twice = finalise(finalise(self._snap()))
        self.assertEqual(once["repos"][0]["needs_you"], twice["repos"][0]["needs_you"])


if __name__ == "__main__":
    unittest.main()
