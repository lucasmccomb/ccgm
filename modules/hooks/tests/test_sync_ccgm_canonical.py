#!/usr/bin/env python3
"""Unit tests for sync-ccgm-canonical hook."""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from importlib.machinery import SourceFileLoader
from unittest.mock import patch

_TEST_DIR = os.path.dirname(os.path.abspath(__file__))
_HOOKS_DIR = os.path.abspath(os.path.join(_TEST_DIR, '..', 'hooks'))
_HOOK_PATH = os.path.join(_HOOKS_DIR, 'sync-ccgm-canonical.py')

sync = SourceFileLoader("sync_ccgm_canonical", _HOOK_PATH).load_module()


class TestRepoDetection(unittest.TestCase):
    def test_is_ccgm_repo_matches_marker(self):
        with patch.object(sync, 'get_origin_url', return_value='git@github.com:testuser/ccgm.git'):
            self.assertTrue(sync.is_ccgm_repo('/any/path'))

    def test_is_ccgm_repo_https_url(self):
        with patch.object(sync, 'get_origin_url', return_value='https://github.com/testuser/ccgm'):
            self.assertTrue(sync.is_ccgm_repo('/any/path'))

    def test_is_ccgm_repo_other_repo(self):
        with patch.object(sync, 'get_origin_url', return_value='git@github.com:testuser/other.git'):
            self.assertFalse(sync.is_ccgm_repo('/any/path'))

    def test_is_ccgm_repo_no_remote(self):
        with patch.object(sync, 'get_origin_url', return_value=None):
            self.assertFalse(sync.is_ccgm_repo('/any/path'))


class TestMergeMatcher(unittest.TestCase):
    """The trigger must fire when `gh pr merge` is any command segment, not only
    when the whole command starts with it. Real merges are cd-prefixed or chained
    (#728)."""

    def test_matches_bare_merge(self):
        self.assertTrue(sync.command_triggers_merge("gh pr merge 5 --squash"))

    def test_matches_cd_prefixed_multiline(self):
        # The common shape: cd into the repo, then merge on the next line.
        self.assertTrue(
            sync.command_triggers_merge(
                "cd /repo/clone\ngh pr merge 727 --squash --delete-branch 2>&1 | tail -5"
            )
        )

    def test_matches_and_chained(self):
        self.assertTrue(sync.command_triggers_merge("cd /repo && gh pr merge 5 --squash"))

    def test_matches_piped(self):
        self.assertTrue(sync.command_triggers_merge("gh pr merge 5 --squash | tail -5"))

    def test_matches_semicolon_chained(self):
        self.assertTrue(sync.command_triggers_merge("cd /repo ; gh pr merge 5"))

    def test_no_match_other_command(self):
        self.assertFalse(sync.command_triggers_merge("ls -la"))

    def test_no_match_gh_pr_view(self):
        self.assertFalse(sync.command_triggers_merge("gh pr view 5"))

    def test_no_match_substring_in_word(self):
        # "merged" / "mergeable" must not trip the (\s|$) boundary.
        self.assertFalse(sync.command_triggers_merge("echo gh pr merged"))


class TestSyncCanonical(unittest.TestCase):
    def test_skips_when_dir_missing_git(self):
        with tempfile.TemporaryDirectory() as tmp:
            ok, msg = sync.sync_canonical(tmp)
            self.assertFalse(ok)
            self.assertIn('not a git repo', msg)


class TestHookRouting(unittest.TestCase):
    """Smoke test the hook's stdin -> behavior routing via subprocess."""

    def _run(self, payload: dict, env: dict | None = None):
        full_env = os.environ.copy()
        full_env.update(env or {})
        return subprocess.run(
            [sys.executable, _HOOK_PATH],
            input=json.dumps(payload),
            capture_output=True, text=True, env=full_env, timeout=10,
        )

    def test_no_op_on_non_bash_tool(self):
        result = self._run({"tool_name": "Read", "tool_input": {}})
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stderr, "")

    def test_no_op_on_non_merge_command(self):
        result = self._run({"tool_name": "Bash", "tool_input": {"command": "ls -la"}})
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stderr, "")

    def test_skips_when_canonical_dir_missing(self):
        with tempfile.TemporaryDirectory() as cwd:
            subprocess.run(["git", "init", "-q", cwd], check=True)
            subprocess.run(
                ["git", "-C", cwd, "remote", "add", "origin",
                 "git@github.com:testuser/ccgm.git"],
                check=True,
            )
            with tempfile.TemporaryDirectory() as fake_home:
                missing = os.path.join(fake_home, "no-such-dir")
                result = self._run(
                    {
                        "tool_name": "Bash",
                        "tool_input": {"command": "gh pr merge 1 --squash"},
                        "cwd": cwd,
                    },
                    env={"CCGM_CANONICAL_DIR": missing},
                )
                self.assertEqual(result.returncode, 0)
                self.assertIn("does not exist", result.stderr)

    def test_cd_prefixed_merge_reaches_sync(self):
        # Regression for #728: a cd-prefixed multiline merge command (the real
        # shape) must get PAST the matcher. With a missing canonical dir it
        # reaches the "does not exist" branch -- proof the matcher fired.
        with tempfile.TemporaryDirectory() as cwd:
            subprocess.run(["git", "init", "-q", cwd], check=True)
            subprocess.run(
                ["git", "-C", cwd, "remote", "add", "origin",
                 "git@github.com:testuser/ccgm.git"],
                check=True,
            )
            with tempfile.TemporaryDirectory() as fake_home:
                missing = os.path.join(fake_home, "no-such-dir")
                result = self._run(
                    {
                        "tool_name": "Bash",
                        "tool_input": {
                            "command": f"cd {cwd}\ngh pr merge 1 --squash --delete-branch 2>&1 | tail -5"
                        },
                        "cwd": cwd,
                    },
                    env={"CCGM_CANONICAL_DIR": missing},
                )
                self.assertEqual(result.returncode, 0)
                self.assertIn("does not exist", result.stderr)

    def test_skips_when_not_ccgm_repo(self):
        with tempfile.TemporaryDirectory() as cwd:
            subprocess.run(["git", "init", "-q", cwd], check=True)
            subprocess.run(
                ["git", "-C", cwd, "remote", "add", "origin",
                 "git@github.com:someone/other-repo.git"],
                check=True,
            )
            result = self._run(
                {
                    "tool_name": "Bash",
                    "tool_input": {"command": "gh pr merge 1 --squash"},
                    "cwd": cwd,
                },
            )
            self.assertEqual(result.returncode, 0)
            self.assertEqual(result.stderr, "")


if __name__ == "__main__":
    unittest.main()
