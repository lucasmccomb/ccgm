#!/usr/bin/env python3
"""Unit tests for agent_sessions tmux state annotation."""

import os
import sys
import unittest

_TEST_DIR = os.path.dirname(os.path.abspath(__file__))
_LIB_DIR = os.path.join(_TEST_DIR, '..', 'lib')
sys.path.insert(0, os.path.abspath(_LIB_DIR))
import agent_sessions


class TestFindTmuxSession(unittest.TestCase):
    def test_returns_session_when_ancestor_is_pane(self):
        # pid 100 -> ppid 50 (tmux pane for session "agents")
        ppid_map = {100: 50, 50: 1}
        pane_pids = {50: "agents"}
        self.assertEqual(
            agent_sessions._find_tmux_session(100, ppid_map, pane_pids),
            "agents",
        )

    def test_walks_multiple_levels(self):
        # pid 100 -> 90 -> 80 -> 50 (pane for "dev")
        ppid_map = {100: 90, 90: 80, 80: 50, 50: 1}
        pane_pids = {50: "dev"}
        self.assertEqual(
            agent_sessions._find_tmux_session(100, ppid_map, pane_pids),
            "dev",
        )

    def test_returns_none_when_no_tmux_ancestor(self):
        ppid_map = {100: 50, 50: 1}
        pane_pids = {999: "other"}
        self.assertIsNone(
            agent_sessions._find_tmux_session(100, ppid_map, pane_pids),
        )

    def test_handles_missing_parent(self):
        ppid_map = {100: 50}  # 50 has no entry
        pane_pids = {}
        self.assertIsNone(
            agent_sessions._find_tmux_session(100, ppid_map, pane_pids),
        )


class TestFormatSessionsText(unittest.TestCase):
    def _base_session(self, **overrides):
        s = {
            "pid": 1234,
            "tty": "ttys001",
            "uptime": "01:00",
            "cwd": "/tmp/foo",
            "repo": "myrepo",
            "branch": "main",
            "agent_id": None,
            "tmux_state": None,
        }
        s.update(overrides)
        return s

    def test_no_tmux_suffix_when_not_in_tmux(self):
        out = agent_sessions.format_sessions_text([self._base_session()])
        self.assertNotIn("[tmux:", out)

    def test_detached_suffix(self):
        out = agent_sessions.format_sessions_text(
            [self._base_session(tmux_state="detached")]
        )
        self.assertIn("[tmux:detached]", out)

    def test_attached_suffix(self):
        out = agent_sessions.format_sessions_text(
            [self._base_session(tmux_state="attached")]
        )
        self.assertIn("[tmux:attached]", out)

    def test_suffix_on_no_repo_row(self):
        out = agent_sessions.format_sessions_text(
            [self._base_session(repo=None, branch=None, tmux_state="detached")]
        )
        self.assertIn("[tmux:detached]", out)


if __name__ == "__main__":
    unittest.main()
