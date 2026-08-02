import unittest
from loom.runner import Result, SubprocessRunner, ReplayRunner


class TestResult(unittest.TestCase):
    def test_ok_is_true_only_for_zero_exit(self):
        self.assertTrue(Result(("git",), "/tmp", 0, "", "").ok)
        self.assertFalse(Result(("git",), "/tmp", 1, "", "boom").ok)


class TestSubprocessRunner(unittest.TestCase):
    def test_captures_stdout_and_exit_code(self):
        r = SubprocessRunner().run(["echo", "hello"], cwd="/tmp")
        self.assertEqual(r.returncode, 0)
        self.assertEqual(r.stdout.strip(), "hello")

    def test_nonzero_exit_is_returned_not_raised(self):
        r = SubprocessRunner().run(["false"], cwd="/tmp")
        self.assertEqual(r.returncode, 1)
        self.assertFalse(r.ok)

    def test_missing_binary_becomes_a_result_not_an_exception(self):
        r = SubprocessRunner().run(["loom-does-not-exist"], cwd="/tmp")
        self.assertFalse(r.ok)
        self.assertIn("not found", r.stderr.lower())


class TestReplayRunner(unittest.TestCase):
    def setUp(self):
        self.runner = ReplayRunner({
            "git status": {"returncode": 0, "stdout": "clean", "stderr": ""},
        })

    def test_serves_the_recording(self):
        r = self.runner.run(["git", "status"], cwd="/repo")
        self.assertEqual(r.stdout, "clean")

    def test_unrecorded_command_raises_loudly(self):
        # A silent empty result here would make every downstream test vacuous.
        with self.assertRaises(KeyError):
            self.runner.run(["git", "log"], cwd="/repo")

    def test_records_every_call_for_assertions(self):
        self.runner.run(["git", "status"], cwd="/repo")
        self.assertEqual(self.runner.calls, [("git", "status")])


if __name__ == "__main__":
    unittest.main()
