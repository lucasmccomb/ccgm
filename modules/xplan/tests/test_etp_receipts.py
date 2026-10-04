"""Tests for ccgm-etp-receipts. gh is stubbed by a fake executable on PATH."""
import json
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

BIN = Path(__file__).resolve().parent.parent / "bin" / "ccgm-etp-receipts"

PR = {
    "number": 7, "url": "https://github.com/o/r/pull/7", "state": "MERGED",
    "mergedAt": "2026-01-01T00:00:00Z", "headRefOid": "aaa",
    "mergeCommit": "bbb", "issues": [5],
    "checks": [{"name": "test", "conclusion": "SUCCESS", "state": ""}],
}


class Verify(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.rec = self.dir / "receipts"
        self.rec.mkdir()
        self.bindir = self.dir / "bin"
        self.bindir.mkdir()
        self.live = self.dir / "live.json"

    def tearDown(self):
        self.tmp.cleanup()

    def run_verify(self, live, receipt=PR):
        self.live.write_text(json.dumps(live))
        gh = self.bindir / "gh"
        gh.write_text(f"#!/bin/sh\ncat '{self.live}'\n")
        gh.chmod(gh.stat().st_mode | stat.S_IEXEC)
        if receipt is not None:
            (self.rec / "5.receipt.json").write_text(json.dumps(receipt))
        env = dict(os.environ, PATH=f"{self.bindir}:{os.environ['PATH']}")
        return subprocess.run([sys.executable, str(BIN), "verify", str(self.rec)],
                              capture_output=True, text=True, env=env)

    def test_matching_receipt_passes(self):
        r = self.run_verify(PR)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("OK", r.stdout)

    def test_skipped_neutral_and_status_context_success_pass(self):
        live = dict(PR, checks=[{"name": "a", "conclusion": "SKIPPED", "state": ""},
                                {"name": "b", "conclusion": "NEUTRAL", "state": ""},
                                {"name": "c", "conclusion": "", "state": "SUCCESS"}])
        self.assertEqual(self.run_verify(live, live).returncode, 0)

    def test_head_sha_mismatch_fails(self):
        r = self.run_verify(dict(PR, headRefOid="zzz"))
        self.assertEqual(r.returncode, 1)
        self.assertIn("headRefOid", r.stdout)

    def test_merge_sha_mismatch_fails(self):
        r = self.run_verify(dict(PR, mergeCommit="zzz"))
        self.assertEqual(r.returncode, 1)
        self.assertIn("mergeCommit", r.stdout)

    def test_unmerged_pr_fails(self):
        r = self.run_verify(dict(PR, state="OPEN", mergeCommit=None))
        self.assertEqual(r.returncode, 1)
        self.assertIn("state", r.stdout)

    def test_failed_check_fails(self):
        live = dict(PR, checks=[{"name": "test", "conclusion": "FAILURE", "state": ""}])
        r = self.run_verify(live)
        self.assertEqual(r.returncode, 1)
        self.assertIn("test", r.stdout)

    def test_pending_check_fails(self):
        live = dict(PR, checks=[{"name": "test", "conclusion": "", "state": "PENDING"}])
        self.assertEqual(self.run_verify(live).returncode, 1)

    def test_invalid_receipt_fails_with_message(self):
        (self.rec / "5.receipt.json").write_text("{not json")
        r = self.run_verify(PR, receipt=None)
        self.assertEqual(r.returncode, 1)
        self.assertIn("invalid", r.stdout)

    def test_receipt_missing_fields_fails(self):
        r = self.run_verify(PR, receipt={"number": 7})
        self.assertEqual(r.returncode, 1)
        self.assertIn("missing", r.stdout)

    def test_empty_dir_exits_2(self):
        r = self.run_verify(PR, receipt=None)
        self.assertEqual(r.returncode, 2)

    def test_missing_dir_exits_2(self):
        r = subprocess.run([sys.executable, str(BIN), "verify", str(self.dir / "nope")],
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 2)


if __name__ == "__main__":
    unittest.main()
