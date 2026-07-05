#!/usr/bin/env python3
"""
Tests for modules/dreaming/lib/apply_dream_proposal.py's adrev-404 wiring:
an UNATTENDED auto-apply of a learning_verify must issue an AUTO verify
(bump uses, do NOT refresh last_verified), while a human /dream-apply accept
of the same kind issues a NORMAL verify (refreshes last_verified). End-to-
end: these drive the real ccgm-learnings-log subprocess, so they prove the
--auto flag is threaded all the way from the apply method down to the store.

Runs in isolation: CCGM_LEARNINGS_DIR + CCGM_DREAMING_DIR are redirected to
tempdirs BEFORE import (mirrors test_reconcile_automemory.py --
learnings_store.LEARNINGS_ROOT is frozen at import time). learnings_store,
dream_analyze, and apply_dream_proposal are popped from sys.modules first so
this file never inherits a stale LEARNINGS_ROOT from whichever test module
pytest collected first in the same process. Each test uses a slug + day +
proposal id unique to that test, so they never interfere despite sharing one
LEARNINGS_ROOT / dreaming dir for the whole file.

Run with: python3 -m pytest modules/dreaming/tests/test_apply_dream_proposal.py -q
      or: python3 modules/dreaming/tests/test_apply_dream_proposal.py
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import time
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "lib"))

# See module docstring: pop first, then point the store + dreaming dir at
# fresh tempdirs, BEFORE importing apply_dream_proposal (which transitively
# imports dream_analyze -> learnings_store, whose LEARNINGS_ROOT is frozen at
# import time).
sys.modules.pop("learnings_store", None)
sys.modules.pop("dream_analyze", None)
sys.modules.pop("apply_dream_proposal", None)

_TMP_LEARNINGS = tempfile.mkdtemp(prefix="ccgm-dreaming-test-applyverify-learnings-")
_TMP_DREAMING = tempfile.mkdtemp(prefix="ccgm-dreaming-test-applyverify-dreaming-")
_TMP_HOME = tempfile.mkdtemp(prefix="ccgm-dreaming-test-applyverify-home-")
_ORIG_LEARNINGS_DIR = os.environ.get("CCGM_LEARNINGS_DIR")
_ORIG_DREAMING_DIR = os.environ.get("CCGM_DREAMING_DIR")
_ORIG_HOME = os.environ.get("HOME")
os.environ["CCGM_LEARNINGS_DIR"] = _TMP_LEARNINGS
os.environ["CCGM_DREAMING_DIR"] = _TMP_DREAMING
# Sandbox HOME so _resolve_sibling_bin() skips the installed
# ~/.claude/bin/ccgm-learnings-log symlink (which points at the canonical
# clone, not this workspace clone under test) and falls back to the
# repo-relative bin -- exactly what test-dream-apply.sh does with HOME_DIR.
os.environ["HOME"] = _TMP_HOME

import apply_dream_proposal as adp  # noqa: E402
import learnings_store as ls  # noqa: E402


def tearDownModule() -> None:
    """Undo the module-level env overrides so they cannot leak into whatever
    test module pytest imports and runs next in the same process (#764)."""
    for key, orig in (
        ("CCGM_LEARNINGS_DIR", _ORIG_LEARNINGS_DIR),
        ("CCGM_DREAMING_DIR", _ORIG_DREAMING_DIR),
        ("HOME", _ORIG_HOME),
    ):
        if orig is not None:
            os.environ[key] = orig
        else:
            os.environ.pop(key, None)


def _proposal_row(*, pid: str, slug: str, target_id: str, confidence: int) -> dict:
    return {
        "id": pid,
        "kind": "learning_verify",
        "project": slug,
        "target_id": target_id,
        "content": None,
        "type": None,
        "confidence": confidence,
        "prevalence": {"sessions": 1, "agents": 1},
        "evidence": [{"session_id": "sess-fixture", "excerpt": "example excerpt"}],
        "justification": "fixture justification",
        "fingerprint": f"fp-{pid}",
        "generated_at": "2026-01-01T00:00:00.000Z",
        "status": "pending",
    }


class AutoApplyVerifyThreadsAutoFlag(unittest.TestCase):
    def setUp(self):
        # Re-assert this module's env at RUN time (not just import time):
        # another test module collected in the same pytest run can have
        # replaced these os.environ values with ITS tempdirs before we run.
        # The ccgm-learnings-log subprocess (invoked deep inside the apply
        # path) reads os.environ fresh, so it must agree with THIS module's
        # in-process learnings_store, whose LEARNINGS_ROOT is frozen. Pinning
        # to str(ls.LEARNINGS_ROOT) guarantees subprocess == in-process store.
        self._pin_env("CCGM_LEARNINGS_DIR", str(ls.LEARNINGS_ROOT))
        self._pin_env("CCGM_DREAMING_DIR", _TMP_DREAMING)
        self._pin_env("HOME", _TMP_HOME)  # so _resolve_sibling_bin uses the repo-relative CLI
        adp.proposals_dir().mkdir(parents=True, exist_ok=True)

    def _pin_env(self, key: str, value: str) -> None:
        had = key in os.environ
        prior = os.environ.get(key)
        os.environ[key] = value

        def _restore() -> None:
            if had:
                os.environ[key] = prior
            else:
                os.environ.pop(key, None)

        self.addCleanup(_restore)

    def _seed_target(self, slug: str) -> str:
        e = ls.build_entry(type_="pattern", content="apply-path verify target", confidence=9)
        e["project"] = slug
        ls.append_entry(e, slug=slug)
        return e["id"]

    def _head(self, slug: str, entry_id: str) -> dict:
        # Force a full replay (no snapshot cache): the verify was written by a
        # SEPARATE ccgm-learnings-log subprocess, so we must re-read the shards
        # rather than trust any cache this process warmed before the write.
        heads = ls.project_slug(slug, use_snapshot=False)["heads"]
        head = next((h for h in heads if h["id"] == entry_id), None)
        self.assertIsNotNone(head, f"target {entry_id} vanished from projection")
        return head

    def _verify_ops(self, slug: str) -> list[dict]:
        """Every `verify` op-row across all agent shards for this slug --
        robust to whatever agent_id the subprocess resolved."""
        agents_dir = ls.project_dir(slug) / "agents"
        ops: list[dict] = []
        for shard in agents_dir.glob("*.jsonl"):
            for ln in shard.read_text().splitlines():
                ln = ln.strip()
                if not ln:
                    continue
                row = json.loads(ln)
                if row.get("op") == "verify":
                    ops.append(row)
        return ops

    def _write_day(self, day: str, row: dict) -> None:
        (adp.proposals_dir() / f"{day}.jsonl").write_text(
            json.dumps(row, sort_keys=True) + "\n", encoding="utf-8"
        )

    def test_auto_apply_issues_auto_verify_no_last_verified_refresh(self):
        slug = f"autoapply-verify-{int(time.time()*1e6)}"
        day = "2026-02-01"
        target_id = self._seed_target(slug)
        orig_lv = self._head(slug, target_id)["last_verified"]

        self._write_day(day, _proposal_row(pid="autoverify01", slug=slug, target_id=target_id, confidence=9))

        summary = adp.run_auto_apply(day)
        self.assertEqual(summary["applied"], 1, summary)
        self.assertEqual(summary["failed"], 0, summary)

        head = self._head(slug, target_id)
        self.assertEqual(head["uses"], 1)
        # THE assertion: an unattended auto-apply verify left last_verified frozen.
        self.assertEqual(head["last_verified"], orig_lv)

        # and the op-row on disk carries `auto: true`
        ops = self._verify_ops(slug)
        self.assertEqual(len(ops), 1)
        self.assertIs(ops[0].get("auto"), True)

        # the proposal was marked auto_applied (positive terminal state)
        _, row = adp.find_proposal("autoverify01")
        self.assertEqual(row["status"], "auto_applied")

    def test_human_accept_issues_normal_verify_refreshing_last_verified(self):
        slug = f"humanaccept-verify-{int(time.time()*1e6)}"
        day = "2026-02-02"
        target_id = self._seed_target(slug)
        orig_lv = self._head(slug, target_id)["last_verified"]

        self._write_day(day, _proposal_row(pid="humanverify01", slug=slug, target_id=target_id, confidence=8))

        result = adp.apply_proposal("humanverify01", method="human_accept", reviewed_by="tester")
        self.assertEqual(result.get("outcome"), "applied", result)

        head = self._head(slug, target_id)
        self.assertEqual(head["uses"], 1)
        # a human accept refreshes last_verified exactly as before adrev-404
        self.assertGreater(ls._parse_iso(head["last_verified"]), ls._parse_iso(orig_lv))

        # and the op-row on disk does NOT carry `auto` (absence == human)
        ops = self._verify_ops(slug)
        self.assertEqual(len(ops), 1)
        self.assertNotIn("auto", ops[0])

        _, row = adp.find_proposal("humanverify01")
        self.assertEqual(row["status"], "accepted")


class RecordReviewReversalTests(unittest.TestCase):
    """Fix 5 (#804): /dream-review's veto/revert must leave an apply-audit
    record (`outcome == "reverted"`, NO `ok`) so Epic 7's scorecard counts
    it under reverted-after-review. Pins BOTH halves of the E6->E7 wiring:
    the on-disk record shape, and that scorecard._aggregate_optimistic()
    actually counts the exact record record_review_reversal() writes."""

    def setUp(self):
        # Fresh CCGM_DREAMING_DIR per test so apply_audit_path() (derived from
        # it) points at a clean, isolated audit log -- the log is cumulative.
        self._dreaming = tempfile.mkdtemp(prefix="ccgm-dreaming-recordrevert-")
        self.addCleanup(shutil.rmtree, self._dreaming, ignore_errors=True)
        self._pin_env("CCGM_DREAMING_DIR", self._dreaming)

    def _pin_env(self, key: str, value: str) -> None:
        had = key in os.environ
        prior = os.environ.get(key)
        os.environ[key] = value

        def _restore():
            if had:
                os.environ[key] = prior
            else:
                os.environ.pop(key, None)

        self.addCleanup(_restore)

    def _audit_rows(self) -> list[dict]:
        path = adp.apply_audit_path()
        if not path.is_file():
            return []
        return [json.loads(ln) for ln in path.read_text().splitlines() if ln.strip()]

    def test_veto_reversal_record_shape(self):
        rec = adp.record_review_reversal(kind="veto", target_id="rowX", reason="wrongly auto-added")
        self.assertEqual(rec["outcome"], "reverted")
        self.assertEqual(rec["kind"], "veto")
        self.assertEqual(rec["target_id"], "rowX")
        self.assertEqual(rec["reason"], "wrongly auto-added")
        # No `ok` field: _aggregate_applied() counts any `ok is True` row as an
        # apply, so a reversal carrying `ok` would be double-counted.
        self.assertNotIn("ok", rec)
        self.assertIn("id", rec)   # stamped by _write_audit
        self.assertIn("ts", rec)   # the field the scorecard windows on

        rows = self._audit_rows()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0], rec, "the on-disk record must be exactly what the function returned")

    def test_revert_reversal_via_cli_writes_record(self):
        rc = adp.main(["record-revert", "--kind", "revert", "--batch-id", "optbatch_abc123"])
        self.assertEqual(rc, 0)
        rows = self._audit_rows()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["outcome"], "reverted")
        self.assertEqual(rows[0]["kind"], "revert")
        self.assertEqual(rows[0]["batch_id"], "optbatch_abc123")
        self.assertNotIn("target_id", rows[0], "no --target-id given -> field omitted")
        self.assertNotIn("ok", rows[0])

    def test_scorecard_aggregate_counts_the_reversal_record(self):
        # The load-bearing E6->E7 assertion: the EXACT record E6 writes is the
        # record E7's aggregator counts as reverted-after-review.
        import scorecard  # same lib dir as apply_dream_proposal (sys.path set above)

        rec = adp.record_review_reversal(kind="veto", target_id="rowY")
        now = time.time()
        opt = scorecard._aggregate_optimistic([rec], now - 3600, now + 3600)  # noqa: SLF001
        self.assertEqual(opt["reverted_total"], 1)
        # ...and it is NOT miscounted as an auto-integrated apply.
        self.assertEqual(opt["auto_integrated_total"], 0)


if __name__ == "__main__":
    unittest.main()
