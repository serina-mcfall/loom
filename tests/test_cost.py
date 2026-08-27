import json
import os
import re
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from loom.agents import PARKED_STALE_SECONDS, WORKING_STALE_SECONDS
from loom import cost as cost_mod
from loom.cost import (ALIAS_MAP, RATES, locate_transcript, read_usage,
                       resolve_model, reset_cache, sum_cost, worktree_cost)

# A fixed clock, the same pattern test_agents.py uses -- worktree_cost
# requires `now` rather than defaulting it, so no test may depend on an
# invisible clock.
NOW = datetime(2026, 8, 27, 12, 0, 0, tzinfo=timezone.utc)


def ago(seconds: float) -> str:
    return (NOW - timedelta(seconds=seconds)).isoformat()


def write_session(state_dir: str, session_id: str, cwd: str, state: str,
                  since: str) -> None:
    Path(state_dir, f"{session_id}.json").write_text(json.dumps(
        {"session_id": session_id, "cwd": cwd, "state": state,
         "since": since, "pid": 1}))


def write_transcript(home: str, cwd: str, session_id: str,
                     records: list[tuple[str, dict]]) -> Path:
    """A .jsonl transcript at the path locate_transcript would derive for
    `cwd` (already resolved -- these fixtures use plain tempdir paths with no
    symlinks, so realpath is the identity)."""
    slug = re.sub(r"[^a-zA-Z0-9]", "-", cwd)
    d = Path(home, ".claude", "projects", slug)
    d.mkdir(parents=True, exist_ok=True)
    path = d / f"{session_id}.jsonl"
    lines = [json.dumps({"message": {"model": m, "usage": u}}) for m, u in records]
    path.write_text("\n".join(lines) + ("\n" if lines else ""))
    return path


def usage(input=0, output=0, cache_read=0, cache_5m=0, cache_1h=0):
    """A usage dict with every bucket present explicitly, defaulting to 0 --
    never by omission, per step 3's absent-bucket rule: a record naming only
    the bucket under test would otherwise trip the "absent from every record"
    rule and blank the very fixture meant to assert a number.
    """
    return {
        "input_tokens": input,
        "output_tokens": output,
        "cache_read_input_tokens": cache_read,
        "cache_creation": {
            "ephemeral_5m_input_tokens": cache_5m,
            "ephemeral_1h_input_tokens": cache_1h,
        },
    }


class TestLocateTranscript(unittest.TestCase):
    def test_literal_slug_directory_with_dot_and_underscore(self):
        # The fixture cwd exercises all three characters where the right rule
        # (every non-alphanumeric char -> "-", nothing prepended) and the
        # wrong rule this plan carried until 2026-08-23 ("-" + cwd.replace("/",
        # "-"), which doubles the leading dash and leaves "." and "_" alone)
        # diverge. The expected directory name below is a HARDCODED LITERAL,
        # never re-derived from locate_transcript's own rule.
        cwd = "/tmp/x/.worktrees/a_b"
        expected_dir = "-tmp-x--worktrees-a-b"
        with tempfile.TemporaryDirectory() as home:
            slug_dir = Path(home, ".claude", "projects", expected_dir)
            slug_dir.mkdir(parents=True)
            transcript = slug_dir / "sess-1.jsonl"
            transcript.write_text("")

            result = locate_transcript(home, cwd, "sess-1")

        self.assertEqual(result, transcript)

    def test_no_matching_file_returns_none(self):
        cwd = "/tmp/x/.worktrees/a_b"
        with tempfile.TemporaryDirectory() as home:
            slug_dir = Path(home, ".claude", "projects", "-tmp-x--worktrees-a-b")
            slug_dir.mkdir(parents=True)
            # A different session id lives here; the one we ask for does not.
            (slug_dir / "sess-1.jsonl").write_text("")

            result = locate_transcript(home, cwd, "sess-does-not-exist")

        self.assertIsNone(result)


class TestReadUsage(unittest.TestCase):
    def test_skips_a_malformed_line_but_keeps_the_well_formed_two_in_order(self):
        line1 = json.dumps({"message": {"model": "claude-opus-5",
                                        "usage": {"input_tokens": 1}}})
        line2 = "{not json"
        line3 = json.dumps({"message": {"model": "claude-sonnet-5",
                                        "usage": {"input_tokens": 2}}})
        with tempfile.TemporaryDirectory() as d:
            path = Path(d, "sess.jsonl")
            path.write_text(f"{line1}\n{line2}\n{line3}\n")

            result = read_usage(path)

        self.assertEqual(result, [
            ("claude-opus-5", {"input_tokens": 1}),
            ("claude-sonnet-5", {"input_tokens": 2}),
        ])

    def test_unreadable_file_raises_oserror_not_an_empty_list(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d, "sess.jsonl")
            path.write_text(json.dumps(
                {"message": {"model": "claude-opus-5", "usage": {}}}) + "\n")
            os.chmod(path, 0o000)
            try:
                with self.assertRaises(OSError):
                    read_usage(path)
            finally:
                os.chmod(path, 0o644)


class TestSumCost(unittest.TestCase):
    # These expected dollar figures are LITERAL, tied to the published rates
    # recorded in the plan (claude-opus-5: 5/25 per MTok input/output),
    # never re-derived from RATES itself -- a wrong rate must fail this,
    # not silently pass because the assertion reads the same table.

    def test_output_only_fixture_prints_25_exactly(self):
        records = [("claude-opus-5", usage(output=1_000_000))]
        result = sum_cost(records)
        self.assertEqual(result["notional_cost_usd"], 25.00)

    def test_one_hour_cache_write_prints_10_not_the_5m_rate_of_6_25(self):
        records = [("claude-opus-5", usage(cache_1h=1_000_000))]
        result = sum_cost(records)
        self.assertEqual(result["notional_cost_usd"], 10.00)

    def test_mixed_model_session_has_a_populated_model_and_both_entries(self):
        records = [
            ("claude-opus-5", usage(output=1_000)),
            ("claude-haiku-4-5-20251001", usage(input=1_000)),
        ]
        result = sum_cost(records)
        self.assertIsNotNone(result["model"])
        self.assertEqual({m["model"] for m in result["models"]},
                         {"claude-opus-5", "claude-haiku-4-5"})

    def test_synthetic_record_prices_the_rest_and_still_returns_a_number(self):
        records = [
            ("claude-opus-5", usage(output=1_000)),
            ("<synthetic>", {"error": "transient API error"}),
        ]
        result = sum_cost(records)
        self.assertIsNotNone(result["notional_cost_usd"])

    def test_unknown_model_id_prints_none(self):
        records = [("totally-unheard-of-model", usage(input=100))]
        result = sum_cost(records)
        self.assertIsNone(result["notional_cost_usd"])

    def test_both_cache_write_ttls_nonzero_combine_into_one_key(self):
        # BOTH TTLs must be non-zero: on this machine 5-minute writes are
        # zero in real data, so a fixture with either at zero would pass
        # under "pick one TTL" just as readily as under addition.
        records = [("claude-opus-5", usage(cache_5m=400_000, cache_1h=600_000))]
        result = sum_cost(records)
        self.assertEqual(result["tokens"]["cache_write_5m"], 400_000)
        self.assertEqual(result["tokens"]["cache_write_1h"], 600_000)
        self.assertEqual(result["tokens"]["cache_write"], 1_000_000)
        self.assertEqual(result["notional_cost_usd"], 8.50)

    def test_every_id_seen_on_disk_resolves_to_a_rate(self):
        # A FROZEN LITERAL LIST -- the union of every id observed on disk on
        # 2026-08-23 and 2026-08-27 -- never re-derived from
        # ~/.claude/projects/ at run time (see step 10 for the separate,
        # skipping, live-corpus test that reads that directory).
        frozen_ids = [
            "claude-opus-5", "claude-sonnet-5", "claude-opus-4-7",
            "claude-haiku-4-5-20251001", "claude-fable-5", "claude-opus-4-8",
        ]
        for model_id in frozen_ids:
            with self.subTest(model_id=model_id):
                self.assertIsNotNone(resolve_model(model_id))

    def test_every_alias_target_is_a_rate_table_key(self):
        for raw_id, target in ALIAS_MAP.items():
            with self.subTest(raw_id=raw_id):
                self.assertIn(target, RATES)

    def test_retired_model_id_prints_none(self):
        # claude-opus-4-20250514: confirmed retired 2026-06-15, unmapped by
        # design -- a rate for it would be a guess with no current price to
        # cite.
        records = [("claude-opus-4-20250514", usage(input=100))]
        result = sum_cost(records)
        self.assertIsNone(result["notional_cost_usd"])

    def test_zero_usage_records_prints_none_not_zero(self):
        result = sum_cost([])
        self.assertIsNone(result["notional_cost_usd"])

    def test_model_field_answers_cost_not_tokens(self):
        # claude-haiku-4-5-20251001: 100,000,000 cache-read tokens, its only
        # bucket -- cost = 100e6 * (1/MTok input rate * 0.1) = $10.00.
        # claude-opus-5: 500,000 output tokens -- cost = 500_000 * 25/MTok =
        # $12.50. Total tokens favour haiku by two orders of magnitude; total
        # cost favours opus-5.
        records = [
            ("claude-haiku-4-5-20251001", usage(cache_read=100_000_000)),
            ("claude-opus-5", usage(output=500_000)),
        ]
        result = sum_cost(records)
        self.assertEqual(result["model"], "claude-opus-5")


class TestWorktreeCost(unittest.TestCase):
    def setUp(self):
        # worktree_cost reads transcripts through cost.py's own module-level
        # (path, mtime, size) cache -- clear it so one test's cached read
        # can never leak into another's.
        reset_cache()
        self._state_td = tempfile.TemporaryDirectory()
        self._home_td = tempfile.TemporaryDirectory()
        self.state_dir = self._state_td.name
        self.home = self._home_td.name

    def tearDown(self):
        self._state_td.cleanup()
        self._home_td.cleanup()
        reset_cache()

    def test_transcript_found_and_complete_is_populated(self):
        cwd = os.path.join(self.state_dir, "wt")
        os.makedirs(cwd)
        write_session(self.state_dir, "s1", cwd, "idle", ago(10))
        write_transcript(self.home, cwd, "s1",
                         [("claude-opus-5", usage(output=1_000))])

        result = worktree_cost(self.state_dir, cwd, [cwd], self.home, NOW)

        self.assertIsNotNone(result["notional_cost_usd"])
        self.assertIsNone(result["unknown_reason"])

    def test_transcript_missing_for_one_of_two_sessions_is_unknown(self):
        cwd = os.path.join(self.state_dir, "wt")
        os.makedirs(cwd)
        write_session(self.state_dir, "s1", cwd, "idle", ago(10))
        write_transcript(self.home, cwd, "s1",
                         [("claude-opus-5", usage(output=1_000))])
        # s2 matches the worktree but has no transcript on disk at all.
        write_session(self.state_dir, "s2", cwd, "idle", ago(10))

        result = worktree_cost(self.state_dir, cwd, [cwd], self.home, NOW)

        self.assertIsNone(result["notional_cost_usd"])
        self.assertEqual(result["unknown_reason"], "transcript-missing")

    def test_transcript_that_raises_on_open_is_unreadable_not_missing(self):
        cwd = os.path.join(self.state_dir, "wt")
        os.makedirs(cwd)
        write_session(self.state_dir, "s1", cwd, "idle", ago(10))
        write_transcript(self.home, cwd, "s1",
                         [("claude-opus-5", usage(output=1_000))])
        write_session(self.state_dir, "s2", cwd, "idle", ago(10))
        unreadable_path = write_transcript(self.home, cwd, "s2",
                                           [("claude-opus-5", usage(output=1_000))])
        os.chmod(unreadable_path, 0o000)
        try:
            result = worktree_cost(self.state_dir, cwd, [cwd], self.home, NOW)
        finally:
            os.chmod(unreadable_path, 0o644)

        self.assertIsNone(result["notional_cost_usd"])
        self.assertEqual(result["unknown_reason"], "unreadable")

    def test_bucket_absent_from_a_summed_record_is_missing_bucket(self):
        cwd = os.path.join(self.state_dir, "wt")
        os.makedirs(cwd)
        write_session(self.state_dir, "s1", cwd, "idle", ago(10))
        # One record explicitly carries every bucket; the other genuinely
        # OMITS cache_read_input_tokens -- the two disagree, so the combined
        # bucket cannot be honestly summed.
        complete = usage(output=1_000)
        incomplete = {"input_tokens": 0, "output_tokens": 500,
                     "cache_creation": {"ephemeral_5m_input_tokens": 0,
                                        "ephemeral_1h_input_tokens": 0}}
        write_transcript(self.home, cwd, "s1", [
            ("claude-opus-5", complete),
            ("claude-opus-5", incomplete),
        ])

        result = worktree_cost(self.state_dir, cwd, [cwd], self.home, NOW)

        self.assertIsNone(result["notional_cost_usd"])
        self.assertEqual(result["unknown_reason"], "missing-bucket")

    def test_one_live_beside_one_stale_sums_both_and_counts_stale(self):
        cwd = os.path.join(self.state_dir, "wt")
        os.makedirs(cwd)
        # working, aged past WORKING_STALE_SECONDS -> stale.
        write_session(self.state_dir, "s1", cwd, "working",
                     ago(WORKING_STALE_SECONDS + 60))
        write_transcript(self.home, cwd, "s1",
                         [("claude-opus-5", usage(output=1_000))])
        # idle, fresh -> live.
        write_session(self.state_dir, "s2", cwd, "idle", ago(5))
        write_transcript(self.home, cwd, "s2",
                         [("claude-opus-5", usage(output=2_000))])

        result = worktree_cost(self.state_dir, cwd, [cwd], self.home, NOW)

        self.assertEqual(result["stale_sessions"], 1)
        self.assertEqual(result["live_sessions"], 1)
        self.assertEqual(result["tokens"]["output"], 3_000)

    def test_stopped_session_eight_hours_old_is_populated_not_unknown(self):
        cwd = os.path.join(self.state_dir, "wt")
        os.makedirs(cwd)
        write_session(self.state_dir, "s1", cwd, "stopped", ago(8 * 3600))
        write_transcript(self.home, cwd, "s1",
                         [("claude-opus-5", usage(output=1_000))])

        result = worktree_cost(self.state_dir, cwd, [cwd], self.home, NOW)

        self.assertIsNotNone(result["tokens"])
        self.assertIsNotNone(result["notional_cost_usd"])
        self.assertEqual(result["stopped_sessions"], 1)
        self.assertEqual(result["live_sessions"], 0)
        self.assertIsNone(result["unknown_reason"])

    def test_zero_matching_sessions_is_no_session(self):
        cwd = os.path.join(self.state_dir, "wt")
        os.makedirs(cwd)
        # A session for a completely different worktree.
        other = os.path.join(self.state_dir, "other")
        os.makedirs(other)
        write_session(self.state_dir, "s1", other, "idle", ago(5))

        result = worktree_cost(self.state_dir, cwd, [cwd, other], self.home, NOW)

        self.assertEqual(result["unknown_reason"], "no-session")
        self.assertEqual(result["live_sessions"], 0)
        self.assertEqual(result["stale_sessions"], 0)
        self.assertEqual(result["stopped_sessions"], 0)
        self.assertEqual(result["undated_sessions"], 0)

    def test_nested_worktree_pair_each_counted_once(self):
        parent = os.path.join(self.state_dir, "r")
        nested = os.path.join(parent, "__worktrees", "a")
        os.makedirs(nested)
        siblings = [parent, nested]

        write_session(self.state_dir, "s-parent", parent, "idle", ago(5))
        write_transcript(self.home, parent, "s-parent",
                         [("claude-opus-5", usage(output=1_000))])
        write_session(self.state_dir, "s-nested", nested, "idle", ago(5))
        write_transcript(self.home, nested, "s-nested",
                         [("claude-opus-5", usage(output=9_000))])

        parent_result = worktree_cost(self.state_dir, parent, siblings, self.home, NOW)
        nested_result = worktree_cost(self.state_dir, nested, siblings, self.home, NOW)

        # Each worktree sums only its OWN session's token count -- neither
        # sees the other's, so this is compared against the known
        # single-session totals rather than merely checking that the total
        # changed.
        self.assertEqual(parent_result["tokens"]["output"], 1_000)
        self.assertEqual(nested_result["tokens"]["output"], 9_000)


class TestTranscriptCache(unittest.TestCase):
    def setUp(self):
        reset_cache()
        self._home_td = tempfile.TemporaryDirectory()

    def tearDown(self):
        self._home_td.cleanup()
        reset_cache()

    def test_reset_cache_clears_a_stale_hit(self):
        path = Path(self._home_td.name, "sess.jsonl")
        line_a = json.dumps({"message": {"model": "claude-opus-5",
                                         "usage": usage(output=1)}})
        line_b = json.dumps({"message": {"model": "claude-opus-5",
                                         "usage": usage(output=2)}})
        # Same length: only the single digit differs, so mtime and size can
        # be made to agree exactly across the rewrite below.
        self.assertEqual(len(line_a), len(line_b))

        path.write_text(line_a + "\n")
        first = cost_mod._read_usage_cached(path)
        self.assertEqual(first, [("claude-opus-5", usage(output=1))])

        st_before = os.stat(path)
        path.write_text(line_b + "\n")
        # Force mtime back to what it was before the rewrite -- proving the
        # cache is keyed on (mtime, size) and genuinely cannot see this
        # change on its own, not merely that the test never triggered a
        # write in practice.
        os.utime(path, (st_before.st_atime, st_before.st_mtime))
        st_after = os.stat(path)
        self.assertEqual(st_after.st_mtime, st_before.st_mtime)
        self.assertEqual(st_after.st_size, st_before.st_size)

        still_cached = cost_mod._read_usage_cached(path)
        self.assertEqual(still_cached, first, "cache hit expected: mtime/size unchanged")

        reset_cache()
        fresh = cost_mod._read_usage_cached(path)
        self.assertEqual(fresh, [("claude-opus-5", usage(output=2))],
                         "reset_cache() must clear the stale entry, not no-op")


if __name__ == "__main__":
    unittest.main()
