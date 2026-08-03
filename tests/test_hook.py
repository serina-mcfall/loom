# tests/test_hook.py
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

    def _notify(self, notification_type=None, include_type=True):
        payload = dict(PAYLOAD)
        if include_type:
            payload["notification_type"] = notification_type
        d = tempfile.mkdtemp()
        handle("Notification", payload, d, "2026-08-03T08:00:00+12:00", 4242)
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

    def test_blocking_and_idle_notification_sets_do_not_overlap(self):
        self.assertEqual(BLOCKING_NOTIFICATIONS & IDLE_NOTIFICATIONS, set())


from loom.hookinstall import merge, install  # noqa: E402


class TestMerge(unittest.TestCase):
    def test_adds_every_event(self):
        self.assertEqual(set(merge({}, "/s/h.py")["hooks"]), set(STATE_FOR_EVENT))

    def test_running_twice_does_not_duplicate(self):
        once = merge({}, "/s/h.py")
        twice = merge(json.loads(json.dumps(once)), "/s/h.py")
        self.assertEqual(len(twice["hooks"]["Stop"]), 1)

    def test_is_idempotent_across_every_event_not_just_one(self):
        once = merge({}, "/s/h.py")
        twice = merge(json.loads(json.dumps(once)), "/s/h.py")
        self.assertEqual(once, twice)

    def test_existing_unrelated_hooks_survive(self):
        existing = {"hooks": {"Stop": [{"hooks": [{"type": "command", "command": "echo hi"}]}]}}
        merged = merge(existing, "/s/h.py")
        commands = [h["command"] for e in merged["hooks"]["Stop"] for h in e["hooks"]]
        self.assertIn("echo hi", commands)
        self.assertEqual(len(commands), 2)

    def test_an_unrelated_event_not_in_state_for_event_is_left_alone(self):
        # A hook on an event Loom doesn't map at all (e.g. PostToolUse) must
        # survive merge() untouched -- merge only ever adds keys it owns.
        existing = {"hooks": {"PostToolUse": [{"hooks": [{"type": "command", "command": "lint.sh"}]}]}}
        merged = merge(existing, "/s/h.py")
        self.assertEqual(merged["hooks"]["PostToolUse"],
                          [{"hooks": [{"type": "command", "command": "lint.sh"}]}])

    def test_merge_touches_no_filesystem(self):
        # merge() is a pure function: a plain dict in, a plain dict out. This
        # is what makes it safe to test at all, given install() would touch
        # an operator's real settings file.
        import inspect
        source = inspect.getsource(merge)
        for forbidden in ("open(", "Path(", ".read_text", ".write_text"):
            self.assertNotIn(forbidden, source)


class TestInstall(unittest.TestCase):
    """install() itself is exercised only against a temp file, never the real
    ~/.claude/settings.json -- see loom/hookinstall.py's module docstring."""

    def test_writes_hooks_to_the_given_temp_path(self):
        d = tempfile.mkdtemp()
        settings_path = str(Path(d, "settings.json"))
        install(settings_path)
        written = json.loads(Path(settings_path).read_text())
        self.assertEqual(set(written["hooks"]), set(STATE_FOR_EVENT))

    def test_preserves_existing_content_at_the_given_temp_path(self):
        d = tempfile.mkdtemp()
        settings_path = str(Path(d, "settings.json"))
        Path(settings_path).write_text(json.dumps({"env": {"SOME_FLAG": "1"}}))
        install(settings_path)
        written = json.loads(Path(settings_path).read_text())
        self.assertEqual(written["env"], {"SOME_FLAG": "1"})


if __name__ == "__main__":
    unittest.main()
