import tempfile
import unittest
from pathlib import Path

from loom.cost import locate_transcript


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


if __name__ == "__main__":
    unittest.main()
