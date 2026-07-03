#!/usr/bin/env python3
"""Tests for modules/dreaming/lib/scorecard.py.

Feeds fixture JSONL (a small learnings store + an injection-log dir + a
proposals dir + an apply-audit file) to scorecard.render() and asserts the
EXACT captured / injected / reused / applied counts, plus the store-health
structural counts. All fixture data is invented (no personal data): slugs like
`acme_widget`, session ids like `sess-1`, learning ids like `L1`.

Determinism: render() takes the window bounds AND generated-at as arguments
(no Date.now in the library), so every assertion here is pinned to a fixed
2026-06-24 → 2026-07-01 window (week ending 2026-06-30). A record stamped
exactly at the window end belongs to the next window and must be excluded --
several fixtures probe that boundary.

`learnings_store` is used by render() only as a pure projection engine
(_project_lines + effective_confidence), so no CCGM_LEARNINGS_DIR redirection
is required for correctness; we still point it at a tempdir defensively so the
import can never touch the real store.

Run with: python3 -m pytest modules/dreaming/tests/test_scorecard.py -q
      or: python3 modules/dreaming/tests/test_scorecard.py
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[2]
sys.path.insert(0, str(HERE.parent / "lib"))                       # dreaming/lib -> scorecard
sys.path.insert(0, str(REPO_ROOT / "modules" / "self-improving" / "lib"))  # -> learnings_store
sys.path.insert(0, str(REPO_ROOT / "modules" / "hooks" / "lib"))           # -> hook_utils

# Defensive: never let the store import bind to the real ~/.claude/learnings.
sys.modules.pop("learnings_store", None)
_TMP_STORE_IMPORT = tempfile.mkdtemp(prefix="ccgm-scorecard-import-")
os.environ["CCGM_LEARNINGS_DIR"] = _TMP_STORE_IMPORT

import scorecard  # noqa: E402
import learnings_store  # noqa: E402


UTC = timezone.utc


def _ts(day: int, hour: int = 9) -> str:
    """A millisecond-precision UTC timestamp on 2026-06-{day}, matching the
    store/injection-log serialization form."""
    return f"2026-06-{day:02d}T{hour:02d}:00:00.000Z"


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r) + "\n")


class ScorecardRenderTest(unittest.TestCase):
    # Week ending 2026-06-30 -> window [2026-06-24 00:00Z, 2026-07-01 00:00Z).
    WINDOW_START = datetime(2026, 6, 24, tzinfo=UTC)
    WINDOW_END = datetime(2026, 7, 1, tzinfo=UTC)
    GENERATED_AT = datetime(2026, 7, 1, 12, 0, tzinfo=UTC)

    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp(prefix="ccgm-scorecard-test-"))
        self.learnings_dir = self.root / "learnings"
        self.injection_dir = self.root / "dreaming" / "injection-log"
        self.proposals_dir = self.root / "dreaming" / "proposals"
        self.audit_path = self.root / "dreaming" / "state" / "apply-audit.jsonl"

        # --- Store op-events across two slugs ------------------------------
        # acme_widget: captures L1,L2 (pattern), L3 (pitfall, later deprecated),
        # plus L4 (pattern) stamped BEFORE the window (must not be captured).
        _write_jsonl(self.learnings_dir / "acme_widget" / "agents" / "agent-a.jsonl", [
            self._add("L1", _ts(25), "pattern", "quote reserved keywords", 9, "acme_widget"),
            self._add("L2", _ts(26), "pattern", "prefer rev-parse over pwd", 9, "acme_widget"),
            self._add("L3", _ts(27), "pitfall", "stash drops untracked files", 9, "acme_widget"),
            self._add("L4", _ts(22), "pattern", "stamped before the window", 9, "acme_widget"),
            self._deprecate("D1", _ts(27, 10), "L3"),
            # Reuses of L1 (x2 in-window) + L2 (x1 in-window); one out-of-window.
            self._verify("V1", _ts(25, 12), "L1"),
            self._verify("V2", _ts(26, 12), "L1"),
            self._verify("V3", _ts(27, 12), "L2"),
            self._verify("V4", _ts(20, 12), "L1"),   # before window -> excluded
        ])
        # demo_app: L5 (tool) superseded by L5b; legacy row L7 (no op field);
        # L6 stamped AFTER the window (must not be captured).
        _write_jsonl(self.learnings_dir / "demo_app" / "agents" / "agent-b.jsonl", [
            self._add("L5", _ts(28), "tool", "tailwind v4 omits cursor pointer", 9, "demo_app"),
            self._supersede("L5b", _ts(30), "L5", "tool",
                            "tailwind v4 preflight omits cursor:pointer", 9, "demo_app"),
            self._add("L6", "2026-07-02T09:00:00.000Z", "tool", "after the window", 9, "demo_app"),
        ])
        _write_jsonl(self.learnings_dir / "demo_app" / "learnings.jsonl", [
            self._legacy("L7", _ts(29), "architecture", "auth runs before rate limiting", 8, "demo_app"),
        ])

        # --- Injection-log telemetry (#782) --------------------------------
        _write_jsonl(self.injection_dir / "2026-06-28.jsonl", [
            self._inj(_ts(25, 8), "sess-1", 2, ["L1", "L2"]),
            self._inj(_ts(26, 8), "sess-1", 1, ["L1"]),          # same session
            self._inj(_ts(27, 8), "sess-2", 3, ["L1", "L3", "L5"]),
            self._inj(_ts(20, 8), "sess-9", 5, ["L1"]),          # before window -> excluded
        ])

        # --- Apply audit + proposals funnel --------------------------------
        _write_jsonl(self.audit_path, [
            self._audit(_ts(25, 13), "learning_verify", ok=True),
            self._audit(_ts(26, 13), "learning_add", ok=True),
            self._audit(_ts(27, 13), "learning_verify", ok=True),
            self._audit(_ts(25, 14), "learning_add", ok=False, outcome="failed_cas"),  # not applied
            self._audit(_ts(20, 13), "learning_add", ok=True),   # before window -> excluded
        ])
        _write_jsonl(self.proposals_dir / "2026-06-28.jsonl", [
            self._proposal(_ts(25, 7), "accepted", "learning_add"),
            self._proposal(_ts(26, 7), "pending", "learning_verify"),
            self._proposal(_ts(27, 7), "auto_applied", "learning_verify"),
            self._proposal(_ts(20, 7), "pending", "learning_add"),  # before window -> excluded
        ])

    # -- op-event / record builders ----------------------------------------
    @staticmethod
    def _add(id_, ts, type_, content, conf, project):
        return {"id": id_, "op": "add", "target_id": None, "timestamp": ts,
                "type": type_, "content": content, "confidence": conf, "project": project}

    @staticmethod
    def _legacy(id_, ts, type_, content, conf, project):
        # A pre-v2 row carries no `op` field and seeds a head verbatim.
        return {"id": id_, "timestamp": ts, "type": type_, "content": content,
                "confidence": conf, "project": project}

    @staticmethod
    def _verify(id_, ts, target):
        return {"id": id_, "op": "verify", "target_id": target, "timestamp": ts}

    @staticmethod
    def _deprecate(id_, ts, target):
        return {"id": id_, "op": "deprecate", "target_id": target, "timestamp": ts}

    @staticmethod
    def _supersede(id_, ts, target, type_, content, conf, project):
        return {"id": id_, "op": "supersede", "target_id": target, "timestamp": ts,
                "type": type_, "content": content, "confidence": conf, "project": project}

    @staticmethod
    def _inj(ts, session, count, ids):
        return {"timestamp": ts, "session_id": session, "source": "startup",
                "project_slug": "acme_widget", "injected_count": count, "injected_ids": ids}

    @staticmethod
    def _audit(ts, kind, *, ok, outcome="applied"):
        return {"id": f"audit_{kind}_{ts}", "ts": ts, "kind": kind,
                "outcome": outcome if ok else outcome, "ok": ok,
                "method": "human_accept", "proposal_id": "p-x"}

    @staticmethod
    def _proposal(generated_at, status, kind):
        return {"id": f"prop-{generated_at}", "generated_at": generated_at,
                "status": status, "kind": kind, "project": "acme_widget"}

    def _render(self) -> str:
        return scorecard.render(
            self.WINDOW_START,
            self.WINDOW_END,
            learnings_dir=self.learnings_dir,
            injection_log_dir=self.injection_dir,
            proposals_dir=self.proposals_dir,
            apply_audit_path=self.audit_path,
            store_api=learnings_store,
            generated_at=self.GENERATED_AT,
        )

    # -- assertions --------------------------------------------------------
    def test_captured_exact(self):
        md = self._render()
        self.assertIn("## Captured — 5 new learnings this window", md)
        self.assertIn("| pattern | acme_widget | 2 |", md)
        self.assertIn("| pitfall | acme_widget | 1 |", md)
        self.assertIn("| tool | demo_app | 1 |", md)
        self.assertIn("| architecture | demo_app | 1 |", md)
        # Out-of-window adds (L4 before, L6 after) are NOT captured.
        self.assertNotIn("6 new learnings", md)
        self.assertNotIn("7 new learnings", md)

    def test_injected_exact(self):
        md = self._render()
        self.assertIn("2 session(s) received injected memory (3 injection event(s))", md)
        self.assertIn("6 total learnings injected", md)
        # L1 injected in all three in-window records; the pre-window record excluded.
        self.assertIn("`L1` — 3×", md)

    def test_reused_exact(self):
        md = self._render()
        self.assertIn("## Reused — 2 learnings reinforced (3 reuse events)", md)
        self.assertIn("`L1` — 2× reused", md)
        self.assertIn("`L2` — 1× reused", md)

    def test_applied_exact(self):
        md = self._render()
        self.assertIn("## Applied — 3 proposals applied this window", md)
        self.assertIn("generated this window: 3 (1 still pending review)", md)
        self.assertIn("applied this window: 3", md)
        self.assertIn("learning_verify: 2", md)
        self.assertIn("learning_add: 1", md)

    def test_store_health_structural(self):
        md = self._render()
        # active = L1,L2,L4,L5b,L6,L7 = 6; L3 deprecated; L5 superseded.
        self.assertIn("## Store health — 6 active learnings", md)
        self.assertIn("deprecated: 1", md)
        self.assertIn("superseded: 1", md)
        # Band counts must partition the active heads.
        bands = {b: int(n) for b, n in re.findall(r"(high|medium|low) \([^)]*\): (\d+)", md)}
        self.assertEqual(sum(bands.values()), 6)

    def test_run_summary_line(self):
        md = self._render()
        self.assertIn(
            "**5 captured · 2 sessions injected · 2 learnings reused (3 events) · 3 applied**",
            md,
        )
        self.assertIn("generated 2026-07-01 12:00 UTC", md)

    def test_returns_str_no_traceback(self):
        md = self._render()
        self.assertIsInstance(md, str)
        self.assertNotIn("Traceback", md)


class ScorecardDegradeTest(unittest.TestCase):
    """Missing/empty sources must render 'no data this window', never raise."""

    def test_all_sources_missing(self):
        root = Path(tempfile.mkdtemp(prefix="ccgm-scorecard-empty-"))
        md = scorecard.render(
            datetime(2026, 6, 24, tzinfo=UTC),
            datetime(2026, 7, 1, tzinfo=UTC),
            learnings_dir=root / "nope-learnings",
            injection_log_dir=root / "nope-injection",
            proposals_dir=root / "nope-proposals",
            apply_audit_path=root / "nope-audit.jsonl",
            store_api=learnings_store,
            generated_at=datetime(2026, 7, 1, tzinfo=UTC),
        )
        self.assertIsInstance(md, str)
        self.assertIn("## Captured — 0 new learnings this window", md)
        self.assertIn("## Store health — 0 active learnings", md)
        self.assertEqual(md.count(scorecard._NO_DATA), 4)  # captured/injected/reused/applied
        self.assertNotIn("Traceback", md)


class ScorecardWrapperSmokeTest(unittest.TestCase):
    """The .sh wrapper resolves the window + wall clock, imports the store via
    the sibling-import helper, writes the file, and prints its path."""

    def test_wrapper_writes_file_and_prints_path(self):
        dreaming_dir = Path(tempfile.mkdtemp(prefix="ccgm-scorecard-wrap-dreaming-"))
        store_dir = Path(tempfile.mkdtemp(prefix="ccgm-scorecard-wrap-store-"))
        # Minimal real store so the health section has something to project.
        _write_jsonl(store_dir / "acme_widget" / "agents" / "agent-a.jsonl", [
            {"id": "W1", "op": "add", "target_id": None, "timestamp": _ts(28),
             "type": "pattern", "content": "smoke test learning", "confidence": 7,
             "project": "acme_widget"},
        ])
        env = dict(os.environ)
        env["CCGM_DREAMING_DIR"] = str(dreaming_dir)
        env["CCGM_LEARNINGS_DIR"] = str(store_dir)
        proc = subprocess.run(
            ["bash", str(REPO_ROOT / "modules" / "dreaming" / "bin" / "dream-scorecard.sh"),
             "2026-06-30"],
            capture_output=True, text=True, env=env,
        )
        self.assertEqual(proc.returncode, 0, msg=f"stderr: {proc.stderr}")
        printed = proc.stdout.strip()
        self.assertTrue(printed.endswith("scorecards/2026-06-30.md"), msg=printed)
        out_file = Path(printed)
        self.assertTrue(out_file.is_file())
        body = out_file.read_text(encoding="utf-8")
        self.assertIn("# Dreaming scorecard — week ending 2026-06-30", body)
        self.assertIn("## Store health — 1 active learnings", body)


if __name__ == "__main__":
    unittest.main()
