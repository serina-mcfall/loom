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

from loom.collect import SCHEMA_VERSION
from loom.view import STALE_AFTER_SECONDS, badge, finalise


def iso(delta_seconds: float = 0.0) -> str:
    when = datetime.now(timezone.utc).astimezone() + timedelta(seconds=delta_seconds)
    return when.isoformat(timespec="seconds")


class TestBadge(unittest.TestCase):
    def test_before_the_first_collection_it_is_connecting_not_live(self):
        b = badge({"schema": SCHEMA_VERSION, "repos": [], "collected": False})
        self.assertEqual(b["state"], "connecting")

    def test_a_fresh_snapshot_is_live(self):
        b = badge({"schema": SCHEMA_VERSION, "collected": True, "generated_at": iso(), "refresh_error": None})
        self.assertEqual(b["state"], "live")

    def test_a_refresh_error_is_an_error_however_fresh_the_stamp(self):
        """THE H6 REGRESSION GUARD.

        `_refresh_step` returns the PREVIOUS snapshot with `refresh_error` set and
        `generated_at` deliberately left unchanged. A freshly-stamped snapshot
        carrying an error must still read as an error -- and the error must win
        over every other signal, because it is the only one that says the data is
        not merely old but actively not being collected.
        """
        b = badge({"schema": SCHEMA_VERSION, "collected": True, "generated_at": iso(),
                   "refresh_error": "KeyError: 'prs'"})
        self.assertEqual(b["state"], "error")
        self.assertIn("KeyError", b["detail"])

    def test_an_old_snapshot_is_stale_even_with_no_error(self):
        b = badge({"schema": SCHEMA_VERSION, "collected": True, "generated_at": iso(-STALE_AFTER_SECONDS - 5),
                   "refresh_error": None})
        self.assertEqual(b["state"], "stale")

    def test_a_snapshot_just_inside_the_window_is_still_live(self):
        b = badge({"schema": SCHEMA_VERSION, "collected": True, "generated_at": iso(-1), "refresh_error": None})
        self.assertEqual(b["state"], "live")

    def test_a_missing_timestamp_is_not_reported_live(self):
        # Cannot tell how old it is, so it must not claim freshness. Silence in the
        # reassuring direction is the failure mode this whole project refuses.
        b = badge({"schema": SCHEMA_VERSION, "collected": True, "refresh_error": None})
        self.assertNotEqual(b["state"], "live")

    def test_a_naive_timestamp_is_not_reported_live(self):
        # A stamp with no offset gives a zone-dependent age -- the exact trap
        # loom/agents.py's `_age_seconds` refuses for hook records.
        b = badge({"schema": SCHEMA_VERSION, "collected": True, "generated_at": "2026-08-05T12:00:00",
                   "refresh_error": None})
        self.assertNotEqual(b["state"], "live")

    def test_an_unparseable_timestamp_is_not_reported_live(self):
        b = badge({"schema": SCHEMA_VERSION, "collected": True, "generated_at": "not a timestamp",
                   "refresh_error": None})
        self.assertNotEqual(b["state"], "live")

    def test_a_future_timestamp_is_not_reported_live(self):
        # Evidence of a broken producer, not of health -- same rule as _age_seconds.
        b = badge({"schema": SCHEMA_VERSION, "collected": True, "generated_at": iso(3600), "refresh_error": None})
        self.assertNotEqual(b["state"], "live")

    def test_every_state_carries_the_staleness_threshold_for_the_page(self):
        """Audit 2026-08-05, M10's other half.

        `/events` no longer suppresses identical frames, so frames ARE the heartbeat:
        silence means the server stopped collecting. The page needs the same
        threshold to notice that silence, and hardcoding it in loom.js would be a
        second copy of a policy that belongs here.
        """
        for snap in ({"schema": SCHEMA_VERSION, "collected": False},
                     {"schema": SCHEMA_VERSION, "collected": True, "generated_at": iso()},
                     {"schema": SCHEMA_VERSION, "collected": True, "generated_at": iso(), "refresh_error": "x"}):
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
            {"schema": SCHEMA_VERSION, "collected": False},
            {"schema": SCHEMA_VERSION, "collected": True, "generated_at": iso()},
            {"schema": SCHEMA_VERSION, "collected": True, "generated_at": iso(-STALE_AFTER_SECONDS - 5)},
            {"schema": SCHEMA_VERSION, "collected": True, "generated_at": iso(), "refresh_error": "boom"},
        ]
        for snap in cases:
            b = badge(snap)
            with self.subTest(state=b["state"]):
                self.assertTrue(b["label"].strip(), "no label")
                # A word, not just a glyph: at least three letters of real text.
                letters = [c for c in b["label"] if c.isalpha()]
                self.assertGreaterEqual(len(letters), 3, f"glyph only: {b['label']!r}")


class TestSchemaIsActuallyChecked(unittest.TestCase):
    """Audit 2026-08-05, part of finding L2.

    The snapshot is versioned, and the spec's stated reason is that "two consumers
    parse it and would otherwise drift silently". Neither consumer ever looked at the
    number. A version field nothing validates is decoration -- it records a promise
    that nothing enforces, which is this project's own definition of a boundary that
    is not a boundary.

    A schema mismatch outranks every other badge state, including a refresh error: if
    the shape cannot be trusted then no field read out of it can be either, and
    reporting "live" over a snapshot this code does not understand would be the worst
    lie available.
    """

    def test_a_matching_schema_is_not_flagged(self):
        from loom.collect import SCHEMA_VERSION
        b = badge({"schema": SCHEMA_VERSION, "collected": True,
                   "generated_at": iso(), "refresh_error": None})
        self.assertEqual(b["state"], "live")

    def test_a_newer_schema_is_refused_rather_than_rendered(self):
        from loom.collect import SCHEMA_VERSION
        b = badge({"schema": SCHEMA_VERSION + 1, "collected": True,
                   "generated_at": iso(), "refresh_error": None})
        self.assertEqual(b["state"], "incompatible")
        self.assertIn(str(SCHEMA_VERSION + 1), b["detail"])

    def test_an_older_schema_is_refused_too(self):
        b = badge({"schema": 0, "collected": True, "generated_at": iso()})
        self.assertEqual(b["state"], "incompatible")

    def test_a_mismatch_outranks_a_refresh_error(self):
        b = badge({"schema": 999, "collected": True, "generated_at": iso(),
                   "refresh_error": "KeyError: 'prs'"})
        self.assertEqual(b["state"], "incompatible")

    def test_a_snapshot_with_no_schema_at_all_is_refused(self):
        # The module-level default before the first tick DOES carry one, so an absent
        # schema means something built this dict that was not `collect`.
        # NO "schema" KEY HERE ON PURPOSE -- that absence is the whole test.
        b = badge({"collected": True, "generated_at": iso()})
        self.assertEqual(b["state"], "incompatible")


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
        return {"schema": SCHEMA_VERSION, "collected": True, "repos": list(repos)}

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


class TestAnnouncement(unittest.TestCase):
    """Audit 2026-08-05, finding M8.

    The strip's 15-second debounce was implemented by flipping `aria-live` between
    "off" and "polite" on every render. Screen readers register live regions when
    they enter the accessibility tree and do not uniformly re-read a changed
    `aria-live` value, so that mechanism may silence the region permanently for some
    readers and not at all for others. The intent was right; the mechanism was the
    fragile way to express it.

    The reliable shape is to stop making the visible list a live region at all: the
    list updates every tick for the eye, and a separate, permanently-polite hidden
    region receives a short summary at most every 15 seconds. What that summary SAYS
    is a decision, so it lives here where it can be asserted -- not in loom.js.
    """

    def _snap(self, *items: dict) -> dict:
        return {"needs_you": list(items)}

    def _item(self, rank: int, label: str, detail: str) -> dict:
        return {"rank": rank, "kind": "k", "subject": label, "label": label,
                "repo": "r", "show_repo": False, "detail": detail}

    def test_a_quiet_fleet_announces_that_it_is_quiet(self):
        from loom.view import announcement
        self.assertEqual(announcement(self._snap()), "Nothing needs you.")

    def test_one_item_is_announced_singularly_with_its_reason(self):
        from loom.view import announcement
        text = announcement(self._snap(self._item(2, "PR #7", "no review yet")))
        self.assertIn("1 item", text)
        self.assertIn("PR #7", text)
        self.assertIn("no review yet", text)

    def test_several_items_are_counted_and_only_the_top_one_is_read_out(self):
        """A screen reader must not be handed the whole strip every 15 seconds.

        The count tells you the size of the problem, the top-ranked item tells you
        where to start, and the visible list is there for everything else.
        """
        from loom.view import announcement
        text = announcement(self._snap(
            self._item(1, "wt-a", "agent is blocked on a prompt"),
            self._item(2, "PR #7", "no review yet"),
            self._item(6, "leftover", "not a git worktree"),
        ))
        self.assertIn("3 items", text)
        self.assertIn("wt-a", text)
        self.assertNotIn("PR #7", text)
        self.assertNotIn("leftover", text)

    def test_the_plural_is_correct(self):
        from loom.view import announcement
        self.assertIn("1 item needs", announcement(
            self._snap(self._item(2, "a", "d"))))
        self.assertIn("2 items need", announcement(
            self._snap(self._item(2, "a", "d"), self._item(3, "b", "d"))))

    def test_finalise_attaches_the_announcement(self):
        snap = finalise({"schema": SCHEMA_VERSION, "collected": True, "repos": []})
        self.assertEqual(snap["announcement"], "Nothing needs you.")


class TestGithubLinks(unittest.TestCase):
    """Spec: 2026-08-06-github-links-design.md.

    A link, not the merge button that was asked for. The button would have inverted the
    threat model -- `gh` is read-only and the server is GET-only, which is the whole
    reason its missing origin check is rated Low -- and GitHub will not let an author
    approve their own PR anyway.

    The URL is built in Python because the page would otherwise scrape "PR #16" for
    digits and cross-reference the repo list for owner/repo, which is the string
    handling finding H8 moved out of loom.js.
    """

    def _repo(self, name, issue_repo, **over):
        base = {"name": name, "issue_repo": issue_repo, "worktrees": [], "prs": [],
                "collisions": [], "flags": [], "issues": [], "sources": []}
        base.update(over)
        return base

    def _pr(self, number, checks="none"):
        return {"number": number, "branch": f"b{number}", "draft": False,
                "review": None, "checks": checks}

    def test_a_pr_item_carries_the_pull_request_url(self):
        snap = finalise({"schema": SCHEMA_VERSION, "collected": True, "repos": [
            self._repo("serina-learning", "launchpad-26/serina-learning",
                       prs=[self._pr(16)])]})
        item = snap["needs_you"][0]
        self.assertEqual(item["url"],
                         "https://github.com/launchpad-26/serina-learning/pull/16")

    def test_the_url_uses_issue_repo_not_the_directory_name(self):
        """THE ONE MOST LIKELY TO BE GOT WRONG.

        The directory is `serina-learning`; the repository is
        `launchpad-26/serina-learning`. Using the directory name yields a plausible URL
        pointing at a repo that does not exist -- worse than no link.
        """
        snap = finalise({"schema": SCHEMA_VERSION, "collected": True, "repos": [
            self._repo("serina-learning", "launchpad-26/serina-learning",
                       prs=[self._pr(16)])]})
        self.assertIn("launchpad-26/serina-learning", snap["needs_you"][0]["url"])

    def test_a_collision_item_has_no_url(self):
        # Negative control: a file across two branches has no single GitHub page.
        snap = finalise({"schema": SCHEMA_VERSION, "collected": True, "repos": [
            self._repo("one", "o/one",
                       collisions=[{"file": "a.ts", "branches": ["x", "y"]}])]})
        item = snap["needs_you"][0]
        self.assertEqual(item["kind"], "collision")
        self.assertIsNone(item["url"])

    def test_an_unresolvable_origin_gives_no_url_rather_than_a_guess(self):
        # issue_repo is null when `git remote get-url origin` did not parse. A link to a
        # 404 is the confident-wrong-answer failure this project refuses.
        snap = finalise({"schema": SCHEMA_VERSION, "collected": True, "repos": [
            self._repo("one", None, prs=[self._pr(16)])]})
        self.assertIsNone(snap["needs_you"][0]["url"])

    def test_an_orphan_pr_flag_links_to_its_pull_request(self):
        snap = finalise({"schema": SCHEMA_VERSION, "collected": True, "repos": [
            self._repo("one", "o/one", prs=[self._pr(16)],
                       flags=[{"kind": "orphan_pr", "severity": "warn",
                               "subject": "PR #16", "pr": 16,
                               "detail": "branch b16 has no worktree"}])]})
        orphan = [i for i in snap["needs_you"] if i["kind"] == "orphan_pr"][0]
        self.assertEqual(orphan["url"], "https://github.com/o/one/pull/16")

    def test_a_stale_dir_flag_has_no_url(self):
        # Negative control for the test above.
        snap = finalise({"schema": SCHEMA_VERSION, "collected": True, "repos": [
            self._repo("one", "o/one",
                       flags=[{"kind": "stale_dir", "severity": "warn",
                               "subject": "leftover", "detail": "not a worktree"}])]})
        self.assertIsNone(snap["needs_you"][0]["url"])


class TestGithubUrl(unittest.TestCase):
    """The builder itself. Issues and pull requests take DIFFERENT paths on github.com
    -- /issues/N and /pull/N -- and getting them the wrong way round produces a URL that
    silently redirects or 404s depending on the number."""

    def test_a_pull_request_path(self):
        from loom.ghsrc import github_url
        self.assertEqual(github_url("o/r", "pull", 16), "https://github.com/o/r/pull/16")

    def test_an_issue_path(self):
        from loom.ghsrc import github_url
        self.assertEqual(github_url("o/r", "issues", 11),
                         "https://github.com/o/r/issues/11")

    def test_no_issue_repo_means_no_url(self):
        from loom.ghsrc import github_url
        self.assertIsNone(github_url(None, "pull", 16))

    def test_no_number_means_no_url(self):
        from loom.ghsrc import github_url
        self.assertIsNone(github_url("o/r", "pull", None))


class TestFinalise(unittest.TestCase):
    """`finalise` is the single boundary both consumers call, so the CLI's JSON and
    the server's SSE frames cannot drift into different shapes -- which is exactly
    how H7 happened."""

    def _snap(self) -> dict:
        return {
            "schema": SCHEMA_VERSION, "collected": True, "generated_at": iso(),
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
