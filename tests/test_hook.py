# tests/test_hook.py
import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from hooks.loom_hook import handle, STATE_FOR_EVENT, BLOCKING_NOTIFICATIONS, IDLE_NOTIFICATIONS

PAYLOAD = {"session_id": "abc123", "cwd": "/t/one", "tool_name": "Bash"}


class TestHandle(unittest.TestCase):
    def _write(self, event, payload=None):
        self.d = tempfile.mkdtemp()
        handle(event, payload or PAYLOAD, self.d, "2026-08-03T08:00:00+12:00", 4242)
        return json.loads(Path(self.d, "abc123.json").read_text())

    def _write_nothing(self, event, payload=None):
        d = tempfile.mkdtemp()
        handle(event, payload or PAYLOAD, d, "2026-08-03T08:00:00+12:00", 4242)
        self.assertEqual(list(Path(d).glob("*.json")), [])

    def test_pretooluse_records_working_and_the_tool(self):
        rec = self._write("PreToolUse")
        self.assertEqual(rec["state"], "working")
        self.assertEqual(rec["tool"], "Bash")

    def test_stop_records_idle(self):
        self.assertEqual(self._write("Stop")["state"], "idle")

    def test_sessionend_records_stopped_and_keeps_the_file(self):
        rec = self._write("SessionEnd")
        self.assertEqual(rec["state"], "stopped")

    def test_the_pid_is_recorded_for_staleness_checks(self):
        self.assertEqual(self._write("SessionStart")["pid"], 4242)

    def test_nothing_from_the_conversation_is_ever_written(self):
        payload = dict(PAYLOAD, prompt="my secret prompt",
                       tool_input={"command": "cat ~/.aws/credentials"},
                       transcript_path="/home/x/.claude/projects/a/b.jsonl")
        rec = self._write("UserPromptSubmit", payload)
        self.assertEqual(set(rec), {"session_id", "cwd", "state", "tool", "since", "pid"})
        self.assertNotIn("secret", json.dumps(rec))
        self.assertNotIn("credentials", json.dumps(rec))

    def test_an_unknown_event_writes_nothing(self):
        self._write_nothing("SomeFutureEvent")

    def test_a_payload_with_no_session_id_writes_nothing(self):
        d = tempfile.mkdtemp()
        handle("Stop", {"cwd": "/t/one"}, d, "T", 1)
        self.assertEqual(list(Path(d).glob("*.json")), [])

    def test_every_mapped_event_has_a_state(self):
        self.assertEqual(set(STATE_FOR_EVENT), {
            "SessionStart", "UserPromptSubmit", "PreToolUse",
            "Notification", "Stop", "SessionEnd"})

    def test_the_writer_and_the_reader_agree_on_where_state_lives(self):
        # Two modules define this constant. If they drift, the dashboard reads an
        # empty directory and reports every agent as unknown, with no error anywhere.
        from hooks.loom_hook import DEFAULT_STATE_DIR as writer
        from loom.agents import DEFAULT_STATE_DIR as reader
        self.assertEqual(writer, reader)


class TestNotificationMapping(unittest.TestCase):
    """Notification fires for several unrelated reasons. Only some of them mean
    a human is actually needed. Mapping everything to "waiting" would report a
    finished agent as blocked on a human -- the dashboard's highest-priority,
    most-trusted row. Each row of the documented notification_type table gets
    its own test so the mapping can never quietly regress to a catch-all.
    """

    def _notify(self, notification_type=None, include_type=True, state_dir=None,
                now="2026-08-03T08:00:00+12:00", pid=4242, payload=None):
        payload = dict(payload or PAYLOAD)
        if include_type:
            payload["notification_type"] = notification_type
        d = state_dir or tempfile.mkdtemp()
        handle("Notification", payload, d, now, pid)
        files = list(Path(d).glob("*.json"))
        if not files:
            return None
        return json.loads(files[0].read_text())

    def test_permission_prompt_records_waiting(self):
        self.assertEqual(self._notify("permission_prompt")["state"], "waiting")

    def test_agent_needs_input_records_waiting(self):
        self.assertEqual(self._notify("agent_needs_input")["state"], "waiting")

    def test_idle_prompt_records_idle(self):
        self.assertEqual(self._notify("idle_prompt")["state"], "idle")

    def test_auth_success_writes_nothing(self):
        self.assertIsNone(self._notify("auth_success"))

    def test_agent_completed_writes_nothing(self):
        self.assertIsNone(self._notify("agent_completed"))

    def test_missing_notification_type_writes_nothing(self):
        self.assertIsNone(self._notify(include_type=False))

    def test_unrecognised_notification_type_writes_nothing(self):
        # The guard that stops the mapping regressing to a catch-all: an
        # entirely unseen type must stay silent, not default to "waiting".
        self.assertIsNone(self._notify("some_future_type"))

    def test_an_unrecognised_notification_leaves_an_existing_state_file_untouched(self):
        # Every other "writes nothing" test above starts from an empty
        # directory, which only proves nothing gets created -- it doesn't
        # prove an existing file survives. Write a real state first, then
        # fire an unrecognised notification at the same session, and assert
        # the file is neither deleted nor rewritten.
        d = tempfile.mkdtemp()
        original = self._notify("permission_prompt", state_dir=d,
                                 now="2026-08-03T08:00:00+12:00", pid=4242)
        self.assertEqual(original["state"], "waiting")
        self._notify("some_future_type", state_dir=d,
                      now="2026-08-03T09:00:00+12:00", pid=9999)
        still_there = json.loads(Path(d, "abc123.json").read_text())
        self.assertEqual(still_there, original)

    def test_blocking_and_idle_notification_sets_do_not_overlap(self):
        self.assertEqual(BLOCKING_NOTIFICATIONS & IDLE_NOTIFICATIONS, set())


from loom.hookinstall import merge, install  # noqa: E402

LOOM_SCRIPT = "/s/loom_hook.py"  # a fake but realistic path: basename matters


class TestMerge(unittest.TestCase):
    def test_adds_every_event(self):
        self.assertEqual(set(merge({}, LOOM_SCRIPT)["hooks"]), set(STATE_FOR_EVENT))

    def test_running_twice_does_not_duplicate(self):
        once = merge({}, LOOM_SCRIPT)
        twice = merge(json.loads(json.dumps(once)), LOOM_SCRIPT)
        self.assertEqual(len(twice["hooks"]["Stop"]), 1)

    def test_is_idempotent_across_every_event_not_just_one(self):
        once = merge({}, LOOM_SCRIPT)
        twice = merge(json.loads(json.dumps(once)), LOOM_SCRIPT)
        self.assertEqual(once, twice)

    def test_existing_unrelated_hooks_survive(self):
        existing = {"hooks": {"Stop": [{"hooks": [{"type": "command", "command": "echo hi"}]}]}}
        merged = merge(existing, LOOM_SCRIPT)
        commands = [h["command"] for e in merged["hooks"]["Stop"] for h in e["hooks"]]
        self.assertIn("echo hi", commands)
        self.assertEqual(len(commands), 2)

    def test_an_unrelated_event_not_in_state_for_event_is_left_alone(self):
        # A hook on an event Loom doesn't map at all (e.g. PostToolUse) must
        # survive merge() untouched -- merge only ever adds keys it owns.
        existing = {"hooks": {"PostToolUse": [{"hooks": [{"type": "command", "command": "lint.sh"}]}]}}
        merged = merge(existing, LOOM_SCRIPT)
        self.assertEqual(merged["hooks"]["PostToolUse"],
                          [{"hooks": [{"type": "command", "command": "lint.sh"}]}])

    def test_relocating_the_script_replaces_the_old_command(self):
        # Self-healing: the dedup used to be an exact string match, so a
        # changed script path (the repo moved) appended a second entry and
        # never removed the first -- a dead command Claude Code keeps trying
        # to run forever. Now the old entry is recognised by loom_hook.py's
        # basename and dropped before the new one is added.
        existing = {"hooks": {"Stop": [{"hooks": [{"type": "command", "command": "echo hi"}]}]}}
        once = merge(existing, "/old/path/loom_hook.py")
        twice = merge(once, "/new/path/loom_hook.py")
        commands = [h["command"] for e in twice["hooks"]["Stop"] for h in e["hooks"]]
        self.assertEqual(commands.count("echo hi"), 1)
        loom_commands = [c for c in commands if c != "echo hi"]
        self.assertEqual(loom_commands, ["python3 /new/path/loom_hook.py Stop"])

    def test_a_non_list_hooks_value_is_skipped_not_crashed_on(self):
        # An operator's hand-edited settings file can hold anything. This must
        # never raise, and Loom's own hook must still get added for the event.
        malformed = {"hooks": {"Stop": [{"hooks": "not-a-list"}]}}
        merged = merge(malformed, LOOM_SCRIPT)  # must not raise
        commands = [h["command"] for e in merged["hooks"]["Stop"]
                    for h in (e.get("hooks") or []) if isinstance(h, dict)]
        self.assertIn(f"python3 {LOOM_SCRIPT} Stop", commands)

    def test_a_non_dict_hook_item_is_skipped_not_crashed_on(self):
        malformed = {"hooks": {"Stop": [{"hooks": ["not-a-dict"]}]}}
        merged = merge(malformed, LOOM_SCRIPT)  # must not raise
        commands = [h["command"] for e in merged["hooks"]["Stop"]
                    for h in (e.get("hooks") or []) if isinstance(h, dict)]
        self.assertIn(f"python3 {LOOM_SCRIPT} Stop", commands)

    def test_merge_never_touches_the_filesystem(self):
        # merge() is a pure function: a plain dict in, a plain dict out. This
        # is what makes it safe to test at all, given install() would touch
        # an operator's real settings file. Prove it for real, not by
        # scanning source text: pass a script path under a directory that
        # does not exist, and confirm merge() never created it -- if merge()
        # touched the filesystem at all (mkdir, write, even just stat-and-
        # raise), something under fake_dir would exist or it would have
        # raised, and it does neither.
        fake_dir = tempfile.mkdtemp()
        missing_parent = str(Path(fake_dir, "does", "not", "exist", "loom_hook.py"))
        merge({}, missing_parent)
        self.assertFalse(Path(fake_dir, "does").exists())


class TestInstall(unittest.TestCase):
    """install() itself is exercised only against a temp file, never the real
    ~/.claude/settings.json -- see loom/hookinstall.py's module docstring."""

    def test_writes_hooks_to_the_given_temp_path(self):
        d = tempfile.mkdtemp()
        settings_path = str(Path(d, "settings.json"))
        with contextlib.redirect_stdout(io.StringIO()):
            install(settings_path)
        written = json.loads(Path(settings_path).read_text())
        self.assertEqual(set(written["hooks"]), set(STATE_FOR_EVENT))

    def test_preserves_existing_content_at_the_given_temp_path(self):
        d = tempfile.mkdtemp()
        settings_path = str(Path(d, "settings.json"))
        Path(settings_path).write_text(json.dumps({"env": {"SOME_FLAG": "1"}}))
        with contextlib.redirect_stdout(io.StringIO()):
            install(settings_path)
        written = json.loads(Path(settings_path).read_text())
        self.assertEqual(written["env"], {"SOME_FLAG": "1"})


class TestStateWriteFailureIsVisible(unittest.TestCase):
    """A hook that cannot write its state must SAY so, not exit 0 and vanish.

    There was no control here, and the handler shipped with a comment asserting
    the opposite of the platform's behaviour: it printed to stderr and returned
    0, "visible in the transcript, so the failure isn't hidden". Measured
    2026-08-06 -- stderr from a hook exiting 0 does not reach the transcript at
    all, so Loom could stop recording state and nothing would say so.

    Exit 2 would be wrong in the other direction: that is the BLOCKING code, and
    a state-recorder must never stop a tool call. Any other non-zero is
    non-blocking and shows its first stderr line, which is what the original
    comment was reaching for. Both halves are asserted below, because a fix that
    made this visible by blocking would be worse than the bug.
    """

    def _run_with_unwritable_state(self):
        import os
        import sys
        from unittest import mock
        from hooks import loom_hook
        payload = json.dumps({"session_id": "t", "hook_event_name": "Stop"})
        err = io.StringIO()
        with mock.patch.object(loom_hook, "handle", side_effect=OSError("read-only file system")), \
             mock.patch.object(sys, "argv", ["loom_hook.py", "Stop"]), \
             mock.patch.object(sys, "stdin", io.StringIO(payload)), \
             contextlib.redirect_stderr(err):
            rc = loom_hook.main()
        return rc, err.getvalue()

    def test_returns_nonzero_so_the_message_reaches_the_transcript(self):
        rc, _ = self._run_with_unwritable_state()
        self.assertNotEqual(rc, 0, "exit 0 is non-blocking but SILENT; the failure would vanish")

    def test_does_not_return_2_because_it_must_never_block_a_tool_call(self):
        rc, _ = self._run_with_unwritable_state()
        self.assertNotEqual(rc, 2, "exit 2 blocks the triggering tool call; a state recorder must not")

    def test_says_what_went_wrong_on_stderr(self):
        _, err = self._run_with_unwritable_state()
        self.assertIn("could not write state", err)
        self.assertIn("read-only file system", err, "the underlying reason must survive into the message")

    def test_a_successful_run_still_exits_zero(self):
        """The positive control. Without it, a handler that always failed would
        satisfy every assertion above."""
        import sys
        from unittest import mock
        from hooks import loom_hook
        payload = json.dumps({"session_id": "t", "hook_event_name": "Stop"})
        with mock.patch.object(loom_hook, "handle", return_value=None), \
             mock.patch.object(sys, "argv", ["loom_hook.py", "Stop"]), \
             mock.patch.object(sys, "stdin", io.StringIO(payload)):
            self.assertEqual(loom_hook.main(), 0)


if __name__ == "__main__":
    unittest.main()
