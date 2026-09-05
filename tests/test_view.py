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


class TestFleetTotal(unittest.TestCase):
    """Step 6: aggregates worktree_cost's per-worktree output (loom/cost.py) to
    fleet level, and is the only place OPEN-2's "N worktrees excluded" and
    OPEN-5's "history, not current burn" labels are built.
    """

    def _cost(self, notional=None, unknown_reason=None, tokens=None,
             prices_as_of="2026-08-27", live=0, stale=0, stopped=0, undated=0):
        return {
            "tokens": tokens, "notional_cost_usd": notional, "model": None,
            "models": [], "prices_as_of": prices_as_of,
            "unknown_reason": unknown_reason,
            "live_sessions": live, "stale_sessions": stale,
            "stopped_sessions": stopped, "undated_sessions": undated,
        }

    def _wt(self, dir_, cost):
        return {"dir": dir_, "cost": cost}

    def _snap(self, *worktrees):
        return {"schema": SCHEMA_VERSION, "collected": True,
                "repos": [{"name": "r", "worktrees": list(worktrees)}]}

    def test_five_worktrees_totals_excludes_and_counts_correctly(self):
        from loom.view import fleet_total
        wts = [
            self._wt("live", self._cost(notional=10.0, live=1)),
            self._wt("stale", self._cost(notional=5.0, stale=1)),
            self._wt("stopped", self._cost(notional=2.5, stopped=1)),
            self._wt("unreadable",
                    self._cost(unknown_reason="unreadable", undated=1)),
            self._wt("quiet", self._cost(unknown_reason="no-session")),
        ]
        result = fleet_total(self._snap(*wts))

        self.assertEqual(result["notional_cost_usd"], 17.5)
        self.assertEqual(result["excluded_count"], 1)
        self.assertIn("1 worktree excluded", result["label"])
        self.assertNotIn("2 worktree", result["label"])
        self.assertIn("list-price equivalent, not a bill", result["label"])
        self.assertIn("1 stale", result["label"])
        self.assertIn("1 stopped", result["label"])
        self.assertIn("2026-08-27", result["label"])

        self.assertEqual(result["live_sessions"], 1)
        self.assertEqual(result["stale_sessions"], 1)
        self.assertEqual(result["stopped_sessions"], 1)
        self.assertEqual(result["undated_sessions"], 1,
                         "undated must be sourced from an UNKNOWN worktree too")

    def test_nested_worktree_pair_through_real_collect_and_fleet_total(self):
        # Mirrors step 4's own nested-worktree fixture, but end to end through
        # collect() -> fleet_total(), the one path that would have caught B1
        # (the double-counting bug) even if the unit-level rule were right but
        # step 5 failed to wire sibling_paths through.
        import json
        import os
        import re
        import tempfile
        from pathlib import Path
        from unittest.mock import patch

        from loom import cost as cost_mod
        from loom.collect import collect
        from loom.runner import ReplayRunner
        from loom.view import fleet_total

        cost_mod.reset_cache()
        parent, nested = "/r", "/r/__worktrees/a"
        worktree_stdout = (
            f"worktree {parent}\nHEAD abc123\nbranch refs/heads/main\n\n"
            f"worktree {nested}\nHEAD def456\nbranch refs/heads/feature-a\n\n"
        )
        recordings = {
            "git symbolic-ref --short refs/remotes/origin/HEAD":
                {"returncode": 0, "stdout": "origin/main\n", "stderr": ""},
            "git worktree list --porcelain":
                {"returncode": 0, "stdout": worktree_stdout, "stderr": ""},
            "tmux list-panes -a -F #{pane_current_path}\t#{pane_current_command}\t"
            "#{pane_pid}\t#{window_name}": {"returncode": 1, "stdout": "", "stderr": ""},
            "git rev-list --left-right --count main...HEAD":
                {"returncode": 0, "stdout": "0\t0\n", "stderr": ""},
            "git status --porcelain=v1 -z": {"returncode": 0, "stdout": "", "stderr": ""},
            "git remote get-url origin":
                {"returncode": 0, "stdout": "git@github.com:you/example.git\n", "stderr": ""},
            "git merge-base main HEAD": {"returncode": 0, "stdout": "base1\n", "stderr": ""},
            "git diff --name-only -z base1 HEAD": {"returncode": 0, "stdout": "", "stderr": ""},
            "git log --all --no-merges -n 40 "
            "--format=%x1e%h%x1f%aI%x1f%s%x1f%D --numstat":
                {"returncode": 0, "stdout": "", "stderr": ""},
        }
        state_dir = tempfile.mkdtemp()
        now_iso = datetime.now(timezone.utc).isoformat()
        Path(state_dir, "s-parent.json").write_text(json.dumps(
            {"session_id": "s-parent", "cwd": parent, "state": "idle",
             "since": now_iso, "pid": 1}))
        Path(state_dir, "s-nested.json").write_text(json.dumps(
            {"session_id": "s-nested", "cwd": nested, "state": "idle",
             "since": now_iso, "pid": 2}))

        home = tempfile.mkdtemp()

        def write_transcript(cwd, session_id, output_tokens):
            slug = re.sub(r"[^a-zA-Z0-9]", "-", cwd)
            d = Path(home, ".claude", "projects", slug)
            d.mkdir(parents=True)
            line = json.dumps({"message": {"model": "claude-opus-5",
                                           "usage": {"input_tokens": 0,
                                                    "output_tokens": output_tokens,
                                                    "cache_read_input_tokens": 0,
                                                    "cache_creation": {
                                                        "ephemeral_5m_input_tokens": 0,
                                                        "ephemeral_1h_input_tokens": 0}}}})
            (d / f"{session_id}.jsonl").write_text(line + "\n")

        # 1,000,000 output tokens on claude-opus-5 (25/MTok) = $25.00 exactly;
        # 2,000,000 = $50.00 -- round literal figures so the total assertion
        # below needs no floating-point rounding.
        write_transcript(parent, "s-parent", 1_000_000)
        write_transcript(nested, "s-nested", 2_000_000)

        with patch.object(cost_mod, "DEFAULT_HOME", home):
            runner = ReplayRunner(recordings)
            snap = collect(runner, "/r", state_dir, include_gh=False)

        result = fleet_total(snap)
        # The sum of the two sessions' own costs exactly once each -- not the
        # parent's cost appearing twice (25.00 + 25.00 + 50.00 = 100.00).
        self.assertEqual(result["notional_cost_usd"], 75.00)

    def test_empty_repos_list_is_cannot_measure_not_measured_and_zero(self):
        from loom.view import fleet_total
        result = fleet_total({"schema": SCHEMA_VERSION, "collected": True, "repos": []})
        self.assertIsNone(result["notional_cost_usd"])
        self.assertEqual(result["excluded_count"], 0)
        self.assertEqual(result["live_sessions"], 0)
        self.assertEqual(result["stale_sessions"], 0)
        self.assertEqual(result["stopped_sessions"], 0)
        self.assertEqual(result["undated_sessions"], 0)

    def test_finalise_attaches_cost_at_the_top_level(self):
        wt = self._wt("live", self._cost(notional=1.0, live=1))
        snap = finalise(self._snap(wt))
        self.assertIn("cost", snap)
        self.assertEqual(snap["cost"]["notional_cost_usd"], 1.0)


if __name__ == "__main__":
    unittest.main()
