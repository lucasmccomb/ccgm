#!/usr/bin/env python3
"""Unit tests for agent_tracking module."""

import csv
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

# Add lib to path (relative to this test file's location in the module)
_TEST_DIR = os.path.dirname(os.path.abspath(__file__))
_LIB_DIR = os.path.join(_TEST_DIR, '..', 'lib')
sys.path.insert(0, os.path.abspath(_LIB_DIR))
import agent_tracking


class TestAgentIdentity(unittest.TestCase):
    """Test agent ID derivation from directory names."""

    def test_workspace_model(self):
        self.assertEqual(
            agent_tracking.get_agent_id("/code/repo-w0-c0"),
            "agent-w0-c0",
        )
        self.assertEqual(
            agent_tracking.get_agent_id("/code/repo-w2-c3"),
            "agent-w2-c3",
        )

    def test_flat_clone_model(self):
        self.assertEqual(
            agent_tracking.get_agent_id("/code/repo-repos/repo-0"),
            "agent-0",
        )
        self.assertEqual(
            agent_tracking.get_agent_id("/code/repo-repos/repo-3"),
            "agent-3",
        )

    def test_default_agent(self):
        self.assertEqual(
            agent_tracking.get_agent_id("/code/some-repo"),
            "agent-0",
        )

    def test_env_clone(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            env_file = os.path.join(tmpdir, ".env.clone")
            with open(env_file, "w") as f:
                f.write("AGENT_ID=agent-w1-c2\nPORT_OFFSET=6\n")
            self.assertEqual(
                agent_tracking.get_agent_id(tmpdir),
                "agent-w1-c2",
            )


class TestCSVOperations(unittest.TestCase):
    """Test CSV read/write with proper quoting."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.repo = "test-repo"
        self.orig_log_repo = agent_tracking.LOG_REPO_DIR
        agent_tracking.LOG_REPO_DIR = self.tmpdir
        os.makedirs(os.path.join(self.tmpdir, self.repo))

    def tearDown(self):
        agent_tracking.LOG_REPO_DIR = self.orig_log_repo
        import shutil
        shutil.rmtree(self.tmpdir)

    def test_init_creates_header(self):
        ok, msg = agent_tracking.init_tracking(self.repo)
        self.assertTrue(ok)
        path = agent_tracking.get_tracking_path(self.repo)
        self.assertTrue(os.path.isfile(path))
        with open(path) as f:
            header = f.readline().strip()
        self.assertEqual(header, ",".join(agent_tracking.CSV_FIELDS))

    def test_init_idempotent(self):
        agent_tracking.init_tracking(self.repo)
        ok, msg = agent_tracking.init_tracking(self.repo)
        self.assertFalse(ok)
        self.assertIn("already exists", msg)

    def test_read_empty_tracking(self):
        agent_tracking.init_tracking(self.repo)
        rows = agent_tracking.read_tracking(self.repo)
        self.assertEqual(rows, [])

    def test_read_nonexistent_tracking(self):
        rows = agent_tracking.read_tracking("no-such-repo")
        self.assertEqual(rows, [])

    def test_write_and_read_roundtrip(self):
        rows = [{
            "issue": "42",
            "agent": "agent-0",
            "status": "in-progress",
            "branch": "42-fix-auth",
            "pr": "",
            "epic": "15",
            "title": "Fix auth token refresh",
            "claimed_at": "2026-03-28T10:00",
            "updated_at": "2026-03-28T10:30",
        }]
        agent_tracking.write_tracking(self.repo, rows)
        result = agent_tracking.read_tracking(self.repo)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["issue"], "42")
        self.assertEqual(result[0]["agent"], "agent-0")
        self.assertEqual(result[0]["title"], "Fix auth token refresh")

    def test_title_with_commas(self):
        """CSV should handle commas in titles correctly."""
        rows = [{
            "issue": "42",
            "agent": "agent-0",
            "status": "in-progress",
            "branch": "42-fix",
            "pr": "",
            "epic": "",
            "title": "Fix auth flow, add tests, update docs",
            "claimed_at": "2026-03-28T10:00",
            "updated_at": "2026-03-28T10:30",
        }]
        agent_tracking.write_tracking(self.repo, rows)
        result = agent_tracking.read_tracking(self.repo)
        self.assertEqual(result[0]["title"], "Fix auth flow, add tests, update docs")

    def test_title_with_quotes(self):
        """CSV should handle quotes in titles correctly."""
        rows = [{
            "issue": "42",
            "agent": "agent-0",
            "status": "in-progress",
            "branch": "42-fix",
            "pr": "",
            "epic": "",
            "title": 'Fix "special" characters',
            "claimed_at": "2026-03-28T10:00",
            "updated_at": "2026-03-28T10:30",
        }]
        agent_tracking.write_tracking(self.repo, rows)
        result = agent_tracking.read_tracking(self.repo)
        self.assertEqual(result[0]["title"], 'Fix "special" characters')


class TestClaimOperations(unittest.TestCase):
    """Test claim, check, release, update operations."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.repo = "test-repo"
        self.orig_log_repo = agent_tracking.LOG_REPO_DIR
        agent_tracking.LOG_REPO_DIR = self.tmpdir
        os.makedirs(os.path.join(self.tmpdir, self.repo))
        agent_tracking.init_tracking(self.repo)
        # Patch commit_and_push to not actually run git
        self.push_patcher = patch.object(
            agent_tracking, "commit_and_push", return_value=True
        )
        self.mock_push = self.push_patcher.start()

    def tearDown(self):
        self.push_patcher.stop()
        agent_tracking.LOG_REPO_DIR = self.orig_log_repo
        import shutil
        shutil.rmtree(self.tmpdir)

    def test_claim_success(self):
        ok, msg = agent_tracking.claim_issue(
            self.repo, 42, agent_id="agent-0", title="Fix auth"
        )
        self.assertTrue(ok)
        self.assertIn("Claimed", msg)

    def test_claim_duplicate_same_agent(self):
        agent_tracking.claim_issue(self.repo, 42, agent_id="agent-0")
        ok, msg = agent_tracking.claim_issue(self.repo, 42, agent_id="agent-0")
        self.assertFalse(ok)
        self.assertIn("already", msg)

    def test_claim_duplicate_different_agent(self):
        agent_tracking.claim_issue(self.repo, 42, agent_id="agent-0")
        ok, msg = agent_tracking.claim_issue(self.repo, 42, agent_id="agent-1")
        self.assertFalse(ok)
        self.assertIn("agent-0", msg)

    def test_claim_after_release(self):
        agent_tracking.claim_issue(self.repo, 42, agent_id="agent-0")
        agent_tracking.release_issue(self.repo, 42, agent_id="agent-0")
        ok, msg = agent_tracking.claim_issue(self.repo, 42, agent_id="agent-1")
        self.assertTrue(ok)

    def test_claim_after_close(self):
        agent_tracking.claim_issue(self.repo, 42, agent_id="agent-0")
        agent_tracking.update_status(self.repo, 42, "closed", agent_id="agent-0")
        ok, msg = agent_tracking.claim_issue(self.repo, 42, agent_id="agent-1")
        self.assertTrue(ok)

    def test_check_claimed(self):
        agent_tracking.claim_issue(self.repo, 42, agent_id="agent-0")
        agent, status = agent_tracking.check_claim(self.repo, 42)
        self.assertEqual(agent, "agent-0")
        self.assertEqual(status, "claimed")

    def test_check_unclaimed(self):
        agent, status = agent_tracking.check_claim(self.repo, 99)
        self.assertIsNone(agent)
        self.assertIsNone(status)

    def test_update_status(self):
        agent_tracking.claim_issue(self.repo, 42, agent_id="agent-0")
        ok, msg = agent_tracking.update_status(
            self.repo, 42, "in-progress", agent_id="agent-0"
        )
        self.assertTrue(ok)
        agent, status = agent_tracking.check_claim(self.repo, 42)
        self.assertEqual(status, "in-progress")

    def test_update_with_pr(self):
        agent_tracking.claim_issue(self.repo, 42, agent_id="agent-0")
        agent_tracking.update_status(
            self.repo, 42, "pr-created", agent_id="agent-0", pr=87
        )
        rows = agent_tracking.read_tracking(self.repo)
        matching = [r for r in rows if r["issue"] == "42" and r["agent"] == "agent-0"
                    and r["status"] == "pr-created"]
        self.assertEqual(len(matching), 1)
        self.assertEqual(matching[0]["pr"], "87")

    def test_update_invalid_status(self):
        agent_tracking.claim_issue(self.repo, 42, agent_id="agent-0")
        ok, msg = agent_tracking.update_status(
            self.repo, 42, "invalid-status", agent_id="agent-0"
        )
        self.assertFalse(ok)
        self.assertIn("Invalid", msg)

    def test_update_wrong_agent(self):
        agent_tracking.claim_issue(self.repo, 42, agent_id="agent-0")
        ok, msg = agent_tracking.update_status(
            self.repo, 42, "in-progress", agent_id="agent-1"
        )
        self.assertFalse(ok)
        self.assertIn("No active claim", msg)

    def test_release(self):
        agent_tracking.claim_issue(self.repo, 42, agent_id="agent-0")
        ok, msg = agent_tracking.release_issue(self.repo, 42, agent_id="agent-0")
        self.assertTrue(ok)
        agent, status = agent_tracking.check_claim(self.repo, 42)
        self.assertIsNone(agent)  # released = terminal, not active


class TestHeartbeat(unittest.TestCase):
    """Test heartbeat throttling."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.repo = "test-repo"
        self.orig_log_repo = agent_tracking.LOG_REPO_DIR
        agent_tracking.LOG_REPO_DIR = self.tmpdir
        os.makedirs(os.path.join(self.tmpdir, self.repo))
        agent_tracking.init_tracking(self.repo)
        self.push_patcher = patch.object(
            agent_tracking, "commit_and_push", return_value=True
        )
        self.push_patcher.start()

    def tearDown(self):
        self.push_patcher.stop()
        agent_tracking.LOG_REPO_DIR = self.orig_log_repo
        import shutil
        shutil.rmtree(self.tmpdir)

    def test_heartbeat_recent_claim_throttled(self):
        """Heartbeat should be throttled if updated recently."""
        agent_tracking.claim_issue(self.repo, 42, agent_id="agent-0")
        updated, msg = agent_tracking.update_heartbeat(
            self.repo, 42, agent_id="agent-0", throttle_minutes=30
        )
        self.assertFalse(updated)
        self.assertIn("throttled", msg)

    def test_heartbeat_old_claim_updates(self):
        """Heartbeat should update if last update is old."""
        agent_tracking.claim_issue(self.repo, 42, agent_id="agent-0")
        # Manually set updated_at to 1 hour ago
        rows = agent_tracking.read_tracking(self.repo)
        from datetime import datetime, timedelta
        old_time = (datetime.now() - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M")
        for row in rows:
            if row["issue"] == "42":
                row["updated_at"] = old_time
        agent_tracking.write_tracking(self.repo, rows)

        updated, msg = agent_tracking.update_heartbeat(
            self.repo, 42, agent_id="agent-0", throttle_minutes=30
        )
        self.assertTrue(updated)
        self.assertIn("updated", msg)


class TestListAndGC(unittest.TestCase):
    """Test list and garbage collection operations."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.orig_log_repo = agent_tracking.LOG_REPO_DIR
        agent_tracking.LOG_REPO_DIR = self.tmpdir
        self.push_patcher = patch.object(
            agent_tracking, "commit_and_push", return_value=True
        )
        self.push_patcher.start()

        # Set up two repos with claims
        for repo in ["repo-a", "repo-b"]:
            os.makedirs(os.path.join(self.tmpdir, repo))
            agent_tracking.init_tracking(repo)

        agent_tracking.claim_issue("repo-a", 1, agent_id="agent-0", title="Issue one")
        agent_tracking.claim_issue("repo-a", 2, agent_id="agent-1", title="Issue two")
        agent_tracking.claim_issue("repo-b", 10, agent_id="agent-0", title="Issue ten")

    def tearDown(self):
        self.push_patcher.stop()
        agent_tracking.LOG_REPO_DIR = self.orig_log_repo
        import shutil
        shutil.rmtree(self.tmpdir)

    def test_list_all(self):
        claims = agent_tracking.list_claims()
        self.assertEqual(len(claims), 3)

    def test_list_by_repo(self):
        claims = agent_tracking.list_claims(repo="repo-a")
        self.assertEqual(len(claims), 2)

    def test_list_by_agent(self):
        claims = agent_tracking.list_claims(agent="agent-0")
        self.assertEqual(len(claims), 2)

    def test_list_by_status(self):
        agent_tracking.update_status("repo-a", 1, "in-progress", agent_id="agent-0")
        claims = agent_tracking.list_claims(status="in-progress")
        self.assertEqual(len(claims), 1)
        self.assertEqual(claims[0]["issue"], "1")

    def test_gc_no_stale(self):
        stale = agent_tracking.gc_stale()
        self.assertEqual(len(stale), 0)

    def test_gc_finds_stale(self):
        # Manually set one claim to be old
        rows = agent_tracking.read_tracking("repo-a")
        from datetime import datetime, timedelta
        old_time = (datetime.now() - timedelta(days=2)).strftime("%Y-%m-%dT%H:%M")
        for row in rows:
            if row["issue"] == "1":
                row["updated_at"] = old_time
        agent_tracking.write_tracking("repo-a", rows)

        stale = agent_tracking.gc_stale()
        self.assertEqual(len(stale), 1)
        self.assertEqual(stale[0]["issue"], "1")

    def test_gc_ignores_terminal(self):
        agent_tracking.update_status("repo-a", 1, "closed", agent_id="agent-0")
        # Even with old date, closed issues aren't stale
        rows = agent_tracking.read_tracking("repo-a")
        from datetime import datetime, timedelta
        old_time = (datetime.now() - timedelta(days=2)).strftime("%Y-%m-%dT%H:%M")
        for row in rows:
            if row["issue"] == "1":
                row["updated_at"] = old_time
        agent_tracking.write_tracking("repo-a", rows)

        stale = agent_tracking.gc_stale()
        self.assertEqual(len(stale), 0)


class TestFormatting(unittest.TestCase):
    """Test display formatting."""

    def test_empty_table(self):
        result = agent_tracking.format_claims_table([])
        self.assertIn("no claims", result)

    def test_table_with_data(self):
        claims = [{
            "issue": "42",
            "agent": "agent-0",
            "status": "in-progress",
            "branch": "42-fix-auth",
            "pr": "",
            "updated_at": "2026-03-28T10:30",
        }]
        result = agent_tracking.format_claims_table(claims)
        self.assertIn("#   42", result)
        self.assertIn("agent-0", result)
        self.assertIn("in-progress", result)


if __name__ == "__main__":
    unittest.main()
