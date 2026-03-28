#!/usr/bin/env python3
"""Unit tests for agent-tracking hooks (pre and post)."""

import json
import os
import sys
import tempfile
import unittest
from unittest.mock import patch, MagicMock

# Add hooks and lib to path
sys.path.insert(0, os.path.expanduser("~/.claude/hooks"))
sys.path.insert(0, os.path.expanduser("~/.claude/lib"))


class TestPreHookPatterns(unittest.TestCase):
    """Test PreToolUse hook command pattern matching."""

    def setUp(self):
        # Import the module fresh
        import importlib
        # We need to test the functions directly
        sys.path.insert(0, os.path.expanduser("~/.claude/hooks"))

    def test_extract_issue_from_branch(self):
        from importlib.machinery import SourceFileLoader
        pre = SourceFileLoader("pre", os.path.expanduser(
            "~/.claude/hooks/agent-tracking-pre.py")).load_module()

        self.assertEqual(pre.extract_issue_from_branch("git checkout -b 42-fix-auth origin/main"), "42")
        self.assertEqual(pre.extract_issue_from_branch("git checkout -b 123-add-tests"), "123")
        self.assertIsNone(pre.extract_issue_from_branch("git checkout main"))
        self.assertIsNone(pre.extract_issue_from_branch("git checkout -b feature-branch"))


class TestPostHookPatterns(unittest.TestCase):
    """Test PostToolUse hook command pattern matching."""

    def setUp(self):
        from importlib.machinery import SourceFileLoader
        self.post = SourceFileLoader("post", os.path.expanduser(
            "~/.claude/hooks/agent-tracking-post.py")).load_module()

    def test_extract_issue_from_branch_cmd(self):
        self.assertEqual(
            self.post.extract_issue_from_branch_cmd("git checkout -b 42-fix-auth origin/main"),
            "42",
        )
        self.assertEqual(
            self.post.extract_issue_from_branch_cmd("git checkout -b 123-add-tests"),
            "123",
        )
        self.assertIsNone(
            self.post.extract_issue_from_branch_cmd("git checkout main")
        )

    def test_extract_issue_from_commit_msg(self):
        self.assertEqual(
            self.post.extract_issue_from_commit_msg('git commit -m "#42: Fix auth"'),
            "42",
        )
        self.assertEqual(
            self.post.extract_issue_from_commit_msg("git commit -m '#123: Add tests'"),
            "123",
        )
        self.assertIsNone(
            self.post.extract_issue_from_commit_msg('git commit -m "No issue ref"')
        )

    def test_extract_branch_name(self):
        self.assertEqual(
            self.post.extract_branch_name("git checkout -b 42-fix-auth origin/main"),
            "42-fix-auth",
        )
        self.assertEqual(
            self.post.extract_branch_name("git checkout -b my-feature"),
            "my-feature",
        )

    def test_extract_pr_number(self):
        self.assertEqual(
            self.post.extract_pr_number("https://github.com/user/repo/pull/87\n"),
            "87",
        )
        self.assertIsNone(
            self.post.extract_pr_number("Created PR successfully")
        )

    def test_extract_issue_from_branch_name(self):
        self.assertEqual(self.post.extract_issue_from_branch_name("42-fix-auth"), "42")
        self.assertEqual(self.post.extract_issue_from_branch_name("123-test"), "123")
        self.assertIsNone(self.post.extract_issue_from_branch_name("feature-branch"))
        self.assertIsNone(self.post.extract_issue_from_branch_name(None))

    def test_is_log_repo(self):
        log_repo = self.post.LOG_REPO_DIR
        self.assertTrue(self.post.is_log_repo(log_repo))
        self.assertTrue(self.post.is_log_repo(os.path.join(log_repo, "some-repo")))
        self.assertFalse(self.post.is_log_repo("/tmp"))
        self.assertFalse(self.post.is_log_repo(os.path.expanduser("~/code/some-other-repos")))


class TestPostHookCommands(unittest.TestCase):
    """Test that the right command patterns trigger the right actions."""

    def setUp(self):
        from importlib.machinery import SourceFileLoader
        self.post = SourceFileLoader("post", os.path.expanduser(
            "~/.claude/hooks/agent-tracking-post.py")).load_module()

    def test_checkout_pattern_matches(self):
        import re
        self.assertTrue(re.match(r"git\s+checkout\s+-b\s+\d+-", "git checkout -b 42-fix"))
        self.assertFalse(re.match(r"git\s+checkout\s+-b\s+\d+-", "git checkout main"))
        self.assertFalse(re.match(r"git\s+checkout\s+-b\s+\d+-", "git checkout -b feature"))

    def test_commit_pattern_matches(self):
        import re
        self.assertTrue(re.match(r"git\s+commit(\s|$)", "git commit -m 'test'"))
        self.assertTrue(re.match(r"git\s+commit(\s|$)", "git commit"))
        self.assertFalse(re.match(r"git\s+commit(\s|$)", "git commit-graph"))

    def test_pr_create_pattern_matches(self):
        import re
        self.assertTrue(re.match(r"gh\s+pr\s+create", "gh pr create --title 'test'"))
        self.assertFalse(re.match(r"gh\s+pr\s+create", "gh pr list"))

    def test_pr_merge_pattern_matches(self):
        import re
        self.assertTrue(re.match(r"gh\s+pr\s+merge", "gh pr merge --squash"))
        self.assertFalse(re.match(r"gh\s+pr\s+merge", "gh pr view"))

    def test_issue_close_pattern(self):
        import re
        match = re.search(r"gh\s+issue\s+close\s+(\d+)", "gh issue close 42")
        self.assertIsNotNone(match)
        self.assertEqual(match.group(1), "42")


if __name__ == "__main__":
    unittest.main()
