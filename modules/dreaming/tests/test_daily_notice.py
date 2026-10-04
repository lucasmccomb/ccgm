#!/usr/bin/env python3
"""
Daily one-line notice (#1098 §3.3, item 2.3).

lib/health.py writes `recent_changes` (the optimistic engine's own
integrations and retirements from the last week) into state/health.json.
hooks/dreaming-health.py turns them into one line for the first session of
the day, and only when something changed since the last notice:

    dreaming: integrated 2 learnings last night (devtrainer: "..."; _global: "...") · retired 1 · /dream-review to veto

`systemMessage` carries the line to the user, `additionalContext` to the
model. A once-per-day sentinel (state/notice.json) keeps later sessions
quiet. A red health notice takes precedence. Nothing is asked.

Run with: python3 -m pytest modules/dreaming/tests/test_daily_notice.py -q
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
MODULE = HERE.parent
sys.path.insert(0, str(MODULE / "lib"))

import health  # noqa: E402

HOOK = MODULE / "hooks" / "dreaming-health.py"
NOW = datetime(2026, 10, 4, 12, 0, tzinfo=timezone.utc)


def _ts(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _env_now(dt: datetime) -> str:
    return _ts(dt)


def open_gate(**_kw):
    return {"state": "open", "code": "ok", "reason": "ok", "since": None}


def applied(kind: str, project: str, content: str | None, when: datetime, method: str = "auto_apply") -> dict:
    row = {"outcome": "applied", "ok": True, "kind": kind, "project": project, "method": method, "ts": _ts(when)}
    if content is not None:
        row["content"] = content
    return row


class NoticeTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        (self.root / "state" / "runs").mkdir(parents=True)
        (self.root / "config.json").write_text(json.dumps({"enabled": True, "optimistic_integration": {"enabled": True}}))
        self.audit = []

    def tearDown(self):
        self._tmp.cleanup()

    def night(self, when: datetime, rows: list) -> None:
        """One nightly run at `when`: append audit rows, write health."""
        self.audit.extend(rows)
        (self.root / "state" / "apply-audit.jsonl").write_text("".join(json.dumps(r) + "\n" for r in self.audit))
        (self.root / "state" / "runs" / f"{when.date().isoformat()}.json").write_text(
            json.dumps({"date": when.date().isoformat(), "generated_at": _ts(when)}))
        health.write(self.root, when, gate_fn=open_gate)

    def session(self, when: datetime) -> str:
        env = {**os.environ, "CCGM_DREAMING_DIR": str(self.root), "CCGM_DREAMING_NOW": _env_now(when), "TZ": "UTC"}
        proc = subprocess.run([sys.executable, str(HOOK)], input='{"hook_event_name":"SessionStart"}',
                              capture_output=True, text=True, env=env, timeout=10)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return proc.stdout

    def standard_night(self) -> None:
        run = NOW - timedelta(hours=9)
        self.night(run, [
            applied("learning_add", "devtrainer", "e2e evidence dir is test-results/e2e under the repo root", run),
            applied("learning_add", "_global", "Read the workspace path before editing a symlinked file", run),
            applied("learning_deprecate", "devtrainer", None, run),
            applied("learning_add", "devtrainer", "A human accepted this one", run, method="human_accept"),
            applied("learning_verify", "devtrainer", None, run),
        ])

    def test_first_session_of_a_day_with_changes_prints_exactly_one_line(self):
        self.standard_night()
        out = json.loads(self.session(NOW))
        line = out["systemMessage"]
        self.assertNotIn("\n", line)
        self.assertTrue(line.startswith("dreaming: integrated 2 learnings last night ("), line)
        self.assertIn('devtrainer: "e2e evidence dir is', line)
        self.assertIn('_global: "Read the workspace path', line)
        self.assertIn("retired 1", line)
        self.assertTrue(line.endswith("/dream-review to veto"), line)
        self.assertNotIn("human accepted", line)
        ctx = out["hookSpecificOutput"]["additionalContext"]
        self.assertEqual(out["hookSpecificOutput"]["hookEventName"], "SessionStart")
        self.assertIn(line, ctx)
        self.assertNotIn("?", line)

    def test_second_session_the_same_day_prints_nothing(self):
        self.standard_night()
        self.session(NOW)
        self.assertEqual(self.session(NOW + timedelta(hours=3)).strip(), "")

    def test_a_day_without_changes_prints_nothing(self):
        self.standard_night()
        self.session(NOW)
        self.night(NOW + timedelta(hours=15), [])
        self.assertEqual(self.session(NOW + timedelta(days=1)).strip(), "")

    def test_never_any_change_prints_nothing(self):
        self.night(NOW - timedelta(hours=9), [])
        self.assertEqual(self.session(NOW).strip(), "")

    def test_the_next_notice_reports_only_what_is_new(self):
        self.standard_night()
        self.session(NOW)
        later = NOW + timedelta(hours=15)
        self.night(later, [applied("learning_supersede", "widget", "Run the formatter before committing", later)])
        line = json.loads(self.session(NOW + timedelta(days=1)))["systemMessage"]
        self.assertTrue(line.startswith('dreaming: integrated 1 learning last night (widget: "Run the formatter'), line)
        self.assertNotIn("devtrainer", line)
        self.assertNotIn("retired", line)

    def test_retired_only(self):
        run = NOW - timedelta(hours=9)
        self.night(run, [applied("learning_contradict", "widget", None, run)])
        line = json.loads(self.session(NOW))["systemMessage"]
        self.assertEqual(line, "dreaming: retired 1 learning last night · /dream-review to veto")

    def test_long_content_is_cut_and_many_slugs_are_summarized(self):
        run = NOW - timedelta(hours=9)
        self.night(run, [applied("learning_add", f"slug{i}", "word " * 40, run) for i in range(5)])
        line = json.loads(self.session(NOW))["systemMessage"]
        self.assertIn("integrated 5 learnings", line)
        self.assertIn("…", line)
        self.assertIn("+2 more", line)
        self.assertLess(len(line), 300)

    def test_changes_from_before_last_night_say_since_when(self):
        # The last session was four days ago; a change from three days ago
        # has not been shown yet.
        (self.root / "state" / "notice.json").write_text(
            json.dumps({"date": "2026-09-30", "checked_at": _ts(NOW - timedelta(days=4))}))
        old = NOW - timedelta(days=3)
        self.night(NOW - timedelta(hours=9), [applied("learning_add", "widget", "Old news but never shown", old)])
        line = json.loads(self.session(NOW))["systemMessage"]
        self.assertIn("integrated 1 learning since 2026-10-01", line)

    def test_red_health_takes_precedence_and_keeps_the_notice_for_later(self):
        self.standard_night()
        h = json.loads((self.root / "state" / "health.json").read_text())
        green = dict(h)
        h["status"] = "red"
        h["reasons"] = [{"code": "analyze_failed", "message": "the analyze step exited 1", "fix": "tail the log"}]
        (self.root / "state" / "health.json").write_text(json.dumps(h))
        out = json.loads(self.session(NOW))
        self.assertNotIn("systemMessage", out)
        self.assertIn('<dreaming-health status="red">', out["hookSpecificOutput"]["additionalContext"])
        (self.root / "state" / "health.json").write_text(json.dumps(green))
        self.assertIn("integrated 2 learnings", json.loads(self.session(NOW + timedelta(hours=1)))["systemMessage"])

    def test_corrupt_sentinel_never_blocks(self):
        self.standard_night()
        (self.root / "state" / "notice.json").write_text("{nope")
        self.assertIn("integrated", json.loads(self.session(NOW))["systemMessage"])


class RecentChangesTest(unittest.TestCase):
    def test_health_lists_only_the_engines_integrations_and_retirements(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "state").mkdir()
            run = NOW - timedelta(hours=2)
            old = NOW - timedelta(days=9)
            rows = [
                applied("learning_add", "a", "kept", run),
                applied("learning_deprecate", "a", None, run),
                applied("learning_add", "a", "human", run, method="human_accept"),
                applied("learning_verify", "a", None, run),
                applied("learning_add", "a", "too old", old),
                {"outcome": "discarded", "reason": "expired", "proposal_id": "x", "ts": _ts(run)},
                {"outcome": "discarded", "reason": "low_confidence", "proposal_id": "y", "ts": _ts(run)},
            ]
            (root / "state" / "apply-audit.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
            h = health.compute(root, NOW, gate_fn=open_gate)
        self.assertEqual([(c["change"], c["content"]) for c in h["recent_changes"]],
                         [("integrated", "kept"), ("retired", None)])
        self.assertEqual((h["expired_last_night"], h["discarded_last_night"]), (1, 2))


if __name__ == "__main__":
    unittest.main()
