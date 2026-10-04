#!/usr/bin/env python3
"""
The digest reports how many friction-only candidates the prefilter left to
autoheal (#1098 Phase 3.2). Drives bin/dream-digest.sh against a run summary.

Run with: python3 -m pytest modules/dreaming/tests/test_friction_digest_line.py -q
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
DREAM_DIGEST = HERE.parent / "bin" / "dream-digest.sh"
DAY = "2026-02-03"


class FrictionDigestLineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.sandbox = Path(tempfile.mkdtemp(prefix="ccgm-friction-digest-test-"))
        self.addCleanup(shutil.rmtree, self.sandbox, ignore_errors=True)
        self.dreaming_dir = self.sandbox / "dreaming"
        self.env = dict(os.environ)
        self.env["HOME"] = str(self.sandbox / "home")
        self.env["CCGM_DREAMING_DIR"] = str(self.dreaming_dir)
        self.env["CCGM_LEARNINGS_DIR"] = str(self.sandbox / "learnings")
        self.env.pop("ANTHROPIC_API_KEY", None)
        self.env["CCGM_LEARNINGS_AUTOCOMMIT"] = "false"
        for d in (self.sandbox / "home", self.sandbox / "learnings", self.dreaming_dir / "state" / "runs"):
            d.mkdir(parents=True)

    def digest(self, prefilter_dropped: dict) -> str:
        summary = {
            "date": DAY, "map_calls": 1, "reduce_calls": 0, "proposals_written": 0,
            "prefilter_dropped": prefilter_dropped,
        }
        (self.dreaming_dir / "state" / "runs" / f"{DAY}.json").write_text(json.dumps(summary), encoding="utf-8")
        proc = subprocess.run(
            ["bash", str(DREAM_DIGEST), DAY], env=self.env, capture_output=True, text=True, timeout=30, check=False,
        )
        self.assertEqual(proc.returncode, 0, msg=proc.stderr)
        return (self.dreaming_dir / "digests" / f"{DAY}.md").read_text(encoding="utf-8")

    def test_digest_counts_friction_only_candidates_left_to_autoheal(self):
        md = self.digest({"already_encoded": 2, "routed_to_autoheal": 3})
        self.assertIn("3 friction-only candidates left to autoheal", md)

    def test_digest_omits_the_line_when_nothing_was_routed(self):
        md = self.digest({"already_encoded": 2, "routed_to_autoheal": 0})
        self.assertNotIn("autoheal", md)


if __name__ == "__main__":
    unittest.main()
