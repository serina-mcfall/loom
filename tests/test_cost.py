import json
import os
import tempfile
import unittest
from pathlib import Path

from loom.cost import locate_transcript, read_usage


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


if __name__ == "__main__":
    unittest.main()
