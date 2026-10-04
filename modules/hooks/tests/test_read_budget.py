#!/usr/bin/env python3
"""Tests for hooks/read-budget.py (PreToolUse:Read size gate)."""

import json
import os
import subprocess
import sys
import tempfile
import unittest

HOOK = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "hooks", "read-budget.py")
)


class ReadBudgetCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = self._tmp.name
        self.state = os.path.join(self.dir, "state")
        self.env_extra = {}

    def tearDown(self):
        self._tmp.cleanup()

    def make(self, name, data):
        path = os.path.join(self.dir, name)
        mode = "wb" if isinstance(data, bytes) else "w"
        with open(path, mode) as f:
            f.write(data)
        return path

    def run_hook(self, path, session="s1", **tool_input):
        env = dict(os.environ)
        for k in list(env):
            if k.startswith("CCGM_READ_BUDGET"):
                del env[k]
        env["CCGM_READ_BUDGET_STATE_DIR"] = self.state
        env.update(self.env_extra)
        payload = {
            "tool_name": "Read",
            "session_id": session,
            "tool_input": {"file_path": path, **tool_input},
        }
        p = subprocess.run(
            [sys.executable, HOOK],
            input=json.dumps(payload),
            capture_output=True,
            text=True,
            env=env,
        )
        self.assertEqual(p.returncode, 0, p.stderr)
        return json.loads(p.stdout) if p.stdout.strip() else None

    def assertDenied(self, out):
        self.assertIsNotNone(out)
        h = out["hookSpecificOutput"]
        self.assertEqual(h["hookEventName"], "PreToolUse")
        self.assertEqual(h["permissionDecision"], "deny")
        return h["permissionDecisionReason"]

    def big_lines(self, name="big.txt", n=2500):
        return self.make(name, "x\n" * n)


class TestDeny(ReadBudgetCase):
    def test_large_file_denied_first_allowed_second(self):
        p = self.big_lines()
        reason = self.assertDenied(self.run_hook(p))
        self.assertIn("Grep", reason)
        self.assertIn("offset", reason)
        self.assertIn("repeat", reason.lower())
        self.assertIsNone(self.run_hook(p))

    def test_byte_threshold(self):
        p = self.make("wide.txt", "a" * 150_000)  # one line, > 100 KB
        self.assertDenied(self.run_hook(p))

    def test_env_line_threshold(self):
        p = self.make("mid.txt", "x\n" * 50)
        self.assertIsNone(self.run_hook(p))
        self.env_extra["CCGM_READ_BUDGET_LINES"] = "10"
        self.assertDenied(self.run_hook(p))

    def test_env_byte_threshold(self):
        p = self.make("mid.txt", "a" * 2000)
        self.env_extra["CCGM_READ_BUDGET_BYTES"] = "1000"
        self.assertDenied(self.run_hook(p))

    def test_sessions_tracked_separately(self):
        p = self.big_lines()
        self.assertDenied(self.run_hook(p, session="a"))
        self.assertDenied(self.run_hook(p, session="b"))
        self.assertIsNone(self.run_hook(p, session="a"))
        self.assertIsNone(self.run_hook(p, session="b"))

    def test_files_tracked_separately(self):
        a, b = self.big_lines("a.txt"), self.big_lines("b.txt")
        self.assertDenied(self.run_hook(a))
        self.assertDenied(self.run_hook(b))


class TestAllow(ReadBudgetCase):
    def test_offset_or_limit_allowed(self):
        p = self.big_lines()
        self.assertIsNone(self.run_hook(p, offset=100))
        self.assertIsNone(self.run_hook(p, limit=200))
        self.assertIsNone(self.run_hook(p, offset=1, limit=200))
        # ranged reads do not consume the one-time warning
        self.assertDenied(self.run_hook(p))

    def test_small_file_allowed(self):
        self.assertIsNone(self.run_hook(self.make("s.txt", "hi\n" * 10)))

    def test_exactly_at_threshold_allowed(self):
        self.assertIsNone(self.run_hook(self.make("e.txt", "x\n" * 2000)))

    def test_allowlisted_extensions(self):
        for name in ("a.png", "a.JPG", "a.pdf", "a.ipynb"):
            p = self.make(name, "x\n" * 5000)
            self.assertIsNone(self.run_hook(p), name)

    def test_binary_allowed(self):
        p = self.make("blob.dat", b"\x00\x01\x02" * 100_000)
        self.assertIsNone(self.run_hook(p))

    def test_missing_file_allowed(self):
        self.assertIsNone(self.run_hook(os.path.join(self.dir, "nope.txt")))

    def test_directory_allowed(self):
        self.assertIsNone(self.run_hook(self.dir))

    def test_off_switch(self):
        p = self.big_lines()
        self.env_extra["CCGM_READ_BUDGET"] = "off"
        self.assertIsNone(self.run_hook(p))

    def test_non_read_tool_ignored(self):
        p = self.big_lines()
        env = dict(os.environ, CCGM_READ_BUDGET_STATE_DIR=self.state)
        r = subprocess.run(
            [sys.executable, HOOK],
            input=json.dumps({"tool_name": "Edit", "tool_input": {"file_path": p}}),
            capture_output=True, text=True, env=env,
        )
        self.assertEqual((r.returncode, r.stdout.strip()), (0, ""))

    def test_bad_input_fails_open(self):
        r = subprocess.run(
            [sys.executable, HOOK], input="not json", capture_output=True, text=True
        )
        self.assertEqual((r.returncode, r.stdout.strip()), (0, ""))

    def test_unwritable_state_fails_open(self):
        p = self.big_lines()
        blocker = self.make("file-not-dir", "x")
        self.state = os.path.join(blocker, "sub")  # cannot be created
        self.run_hook(p)  # must not crash (exit 0 asserted in run_hook)


if __name__ == "__main__":
    unittest.main()
