#!/usr/bin/env python3
"""Unit tests for the `paths:` version floor (Epic 1, issue #954).

Covers `lib/rule_tiering.py`'s `claude_code_supports_paths()`:

  - explicit version strings below / at / above MIN_SUPPORTED_VERSION
    (2.1.207 -- plan.md §1.2 insight 1 / R6)
  - unparseable input is fail-safe (False), never "assume supported"
  - the real `claude --version` output shape ("2.1.220 (Claude Code)")
    parses correctly
  - the no-argument (subprocess) path is exercised via mocking only, so
    this test is fully deterministic and needs no `claude` CLI on PATH
    -- required for the deterministic CI gate, which has neither
    (plan.md §8.4)
"""
import os
import subprocess
import sys
import unittest
from unittest import mock

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.abspath(os.path.join(_HERE, "..", "..", "..", "lib"))
sys.path.insert(0, _REPO_ROOT)

import rule_tiering  # noqa: E402


class ExplicitVersionStringTests(unittest.TestCase):
    """No subprocess involved -- pure string parsing."""

    def test_below_floor_returns_false(self):
        self.assertFalse(rule_tiering.claude_code_supports_paths("2.1.206"))

    def test_below_floor_returns_false_with_real_cli_suffix(self):
        self.assertFalse(rule_tiering.claude_code_supports_paths("2.1.206 (Claude Code)"))

    def test_at_floor_returns_true(self):
        self.assertTrue(rule_tiering.claude_code_supports_paths("2.1.207"))

    def test_above_floor_returns_true(self):
        self.assertTrue(rule_tiering.claude_code_supports_paths("2.1.220"))

    def test_above_floor_returns_true_with_real_cli_suffix(self):
        # This is the exact stdout shape observed from `claude --version`
        # on 2.1.220 (recorded in decisions.md).
        self.assertTrue(rule_tiering.claude_code_supports_paths("2.1.220 (Claude Code)"))

    def test_much_older_major_version_returns_false(self):
        self.assertFalse(rule_tiering.claude_code_supports_paths("1.9.999"))

    def test_much_newer_version_returns_true(self):
        self.assertTrue(rule_tiering.claude_code_supports_paths("3.0.0"))


class UnparseableInputIsFailSafeTests(unittest.TestCase):
    """An unparseable version must never be treated as 'supported'."""

    def test_empty_string_returns_false(self):
        self.assertFalse(rule_tiering.claude_code_supports_paths(""))

    def test_garbage_text_returns_false(self):
        self.assertFalse(rule_tiering.claude_code_supports_paths("not a version at all"))

    def test_whitespace_only_returns_false(self):
        self.assertFalse(rule_tiering.claude_code_supports_paths("   \n\t  "))

    def test_non_string_input_returns_false(self):
        # Defensive: a caller passing the wrong type must not raise or
        # be silently treated as supported.
        self.assertFalse(rule_tiering.claude_code_supports_paths(12345))  # type: ignore[arg-type]


class SubprocessFallbackTests(unittest.TestCase):
    """version_string=None shells out to `claude --version`. Mocked in
    every case so these tests are deterministic regardless of whether
    the `claude` CLI is installed on the machine running them."""

    def test_uses_claude_version_when_not_supplied(self):
        completed = subprocess.CompletedProcess(
            args=["claude", "--version"], returncode=0, stdout="2.1.220 (Claude Code)\n", stderr=""
        )
        with mock.patch.object(rule_tiering.subprocess, "run", return_value=completed) as run:
            self.assertTrue(rule_tiering.claude_code_supports_paths())
        run.assert_called_once()
        called_args = run.call_args[0][0]
        self.assertIn("claude", called_args)
        self.assertIn("--version", called_args)

    def test_subprocess_below_floor_returns_false(self):
        completed = subprocess.CompletedProcess(
            args=["claude", "--version"], returncode=0, stdout="2.1.206 (Claude Code)\n", stderr=""
        )
        with mock.patch.object(rule_tiering.subprocess, "run", return_value=completed):
            self.assertFalse(rule_tiering.claude_code_supports_paths())

    def test_subprocess_unparseable_output_is_fail_safe(self):
        completed = subprocess.CompletedProcess(
            args=["claude", "--version"], returncode=0, stdout="not a version\n", stderr=""
        )
        with mock.patch.object(rule_tiering.subprocess, "run", return_value=completed):
            self.assertFalse(rule_tiering.claude_code_supports_paths())

    def test_claude_cli_not_found_is_fail_safe(self):
        # The deterministic CI gate has no `claude` CLI at all (plan.md
        # §8.4) -- this must not raise, and must not be treated as
        # "supported".
        with mock.patch.object(rule_tiering.subprocess, "run", side_effect=FileNotFoundError):
            self.assertFalse(rule_tiering.claude_code_supports_paths())

    def test_subprocess_timeout_is_fail_safe(self):
        with mock.patch.object(
            rule_tiering.subprocess,
            "run",
            side_effect=subprocess.TimeoutExpired(cmd="claude --version", timeout=10),
        ):
            self.assertFalse(rule_tiering.claude_code_supports_paths())


if __name__ == "__main__":
    unittest.main()
