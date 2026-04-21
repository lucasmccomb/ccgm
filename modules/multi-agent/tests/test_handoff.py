#!/usr/bin/env python3
"""Tests for the multi-agent handoff lib."""
from __future__ import annotations

import importlib.util
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path


def _load():
    """Load the handoff module from the sibling lib directory."""
    here = Path(__file__).resolve().parent
    lib = here.parent / "lib" / "handoff.py"
    spec = importlib.util.spec_from_file_location("handoff", str(lib))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class HandoffTestCase(unittest.TestCase):
    """All tests redirect HANDOFFS_ROOT to a tmp dir so they don't touch real state."""

    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp(prefix="handoff-test-")
        os.environ["CCGM_HANDOFFS_DIR"] = self.tmp
        # Reload to pick up new env
        self.ho = _load()
        # Explicit override in case of caching
        self.ho.HANDOFFS_ROOT = Path(self.tmp)

    def tearDown(self) -> None:
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)
        os.environ.pop("CCGM_HANDOFFS_DIR", None)

    def _write(self, **kw) -> Path:
        defaults = dict(
            body="# H\n## What I did\nThing.\n## What's next\nMore.\n## Blockers / context\nNone.\n",
            repo="ccgm",
            agent="agent-w0-c0",
        )
        defaults.update(kw)
        return self.ho.write_handoff(**defaults)

    def test_slugify_repo(self) -> None:
        self.assertEqual(self.ho.slugify_repo("ccgm"), "ccgm")
        self.assertEqual(self.ho.slugify_repo("my/repo"), "my-repo")
        self.assertEqual(self.ho.slugify_repo("  "), "unknown")

    def test_write_creates_file_with_frontmatter(self) -> None:
        dest = self._write(branch="b", pr=42, issue=40, title="Fix X")
        self.assertTrue(dest.exists())
        content = dest.read_text()
        self.assertIn("agent: agent-w0-c0", content)
        self.assertIn("repo: ccgm", content)
        self.assertIn("branch: b", content)
        self.assertIn("pr: 42", content)
        self.assertIn("issue: 40", content)
        self.assertIn("title: Fix X", content)
        self.assertIn("## What I did", content)

    def test_list_peer_handoffs_excludes_self(self) -> None:
        self._write(agent="agent-w0-c0", when=datetime.now(timezone.utc) - timedelta(hours=1))
        self._write(agent="agent-w0-c1", when=datetime.now(timezone.utc) - timedelta(hours=2))
        peers = self.ho.list_peer_handoffs("ccgm", this_agent="agent-w0-c0", days=7)
        self.assertEqual(len(peers), 1)
        self.assertEqual(peers[0]["agent"], "agent-w0-c1")

    def test_list_peer_handoffs_time_window(self) -> None:
        self._write(agent="agent-1", when=datetime.now(timezone.utc) - timedelta(days=10))
        peers = self.ho.list_peer_handoffs("ccgm", this_agent="agent-0", days=7)
        self.assertEqual(peers, [])

    def test_list_peer_handoffs_newest_first(self) -> None:
        old = self._write(agent="agent-old", when=datetime.now(timezone.utc) - timedelta(hours=6))
        new = self._write(agent="agent-new", when=datetime.now(timezone.utc) - timedelta(hours=1))
        peers = self.ho.list_peer_handoffs("ccgm", this_agent="agent-0", days=7)
        self.assertEqual(peers[0]["agent"], "agent-new")
        self.assertEqual(peers[1]["agent"], "agent-old")

    def test_prune_old_handoffs(self) -> None:
        # Two old, one new
        self._write(agent="a", when=datetime.now(timezone.utc) - timedelta(days=40))
        self._write(agent="b", when=datetime.now(timezone.utc) - timedelta(days=35))
        self._write(agent="c", when=datetime.now(timezone.utc) - timedelta(days=5))
        n = self.ho.prune_old_handoffs(repo="ccgm", days=30)
        self.assertEqual(n, 2)
        remaining = list((Path(self.tmp) / "ccgm").glob("*.md"))
        self.assertEqual(len(remaining), 1)

    def test_summarize_for_startup_empty(self) -> None:
        self.assertIsNone(
            self.ho.summarize_for_startup("ccgm", this_agent="agent-0")
        )

    def test_summarize_for_startup_renders_block(self) -> None:
        self._write(
            agent="agent-w0-c1",
            title="Ship login flow",
            when=datetime.now(timezone.utc) - timedelta(hours=2),
        )
        block = self.ho.summarize_for_startup("ccgm", this_agent="agent-w0-c0")
        self.assertIsNotNone(block)
        self.assertIn("<peer-handoffs>", block)
        self.assertIn("agent-w0-c1", block)
        self.assertIn("Ship login flow", block)

    def test_filename_parse_roundtrip(self) -> None:
        ts = datetime(2026, 4, 21, 12, 30, 45, tzinfo=timezone.utc)
        dest = self._write(agent="agent-1", when=ts)
        parsed = self.ho._parse_filename(dest)
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed[0].strftime("%Y-%m-%dT%H-%M-%S"), "2026-04-21T12-30-45")
        self.assertEqual(parsed[1], "agent-1")

    def test_write_requires_repo_and_agent(self) -> None:
        with self.assertRaises(ValueError):
            self.ho.write_handoff(body="x", repo="", agent="a")
        with self.assertRaises(ValueError):
            self.ho.write_handoff(body="x", repo="ccgm", agent="")


if __name__ == "__main__":
    unittest.main()
