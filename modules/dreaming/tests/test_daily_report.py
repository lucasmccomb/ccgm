#!/usr/bin/env python3
"""
Tests for the "Applied this run (auto)" section of
modules/dreaming/bin/dream-digest.sh (optimistic-memory plan.md Section 5
Epic 5).

dream-digest.sh keeps its ENTIRE rendering logic inline (a python3 heredoc
inside the bash script) rather than an importable lib/*.py module -- Epic 5's
own spec scopes changes to that one file plus this test, so these tests drive
the script exactly the way a real nightly run would: as a subprocess, reading
its stdout/exit code and the digests/{date}.md + state/surfaced/*.json files
it writes. No apply_dream_proposal.py/learnings_store.py import happens here
(everything the digest needs is either read straight off disk or produced by
a real `ccgm-learnings-log` subprocess), so there is no module-level
CCGM_LEARNINGS_DIR-frozen-at-import-time concern to manage -- each fixture
just sets the env dict passed to subprocess.run().

Isolated: every test gets its own mktemp sandbox (dreaming dir, learnings
dir, home dir); nothing ever touches the real ~/.claude/{dreaming,learnings}
(#793). Never touches the network.

Run with: python3 -m pytest modules/dreaming/tests/test_daily_report.py -q
      or: python3 modules/dreaming/tests/test_daily_report.py
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
MODULE_ROOT = HERE.parent
REPO_ROOT = HERE.parents[2]

DREAM_DIGEST = MODULE_ROOT / "bin" / "dream-digest.sh"
LEARNINGS_LOG = REPO_ROOT / "modules" / "self-improving" / "bin" / "ccgm-learnings-log"


def _content_sha256(content: str) -> str:
    """Mirrors learnings_store.content_sha256() exactly (sha256 hex of the
    UTF-8 encoded content) -- reimplemented here, not imported, so this test
    never needs to import learnings_store (see module docstring)."""
    return hashlib.sha256((content or "").encode("utf-8")).hexdigest()


def _iso(dt_obj: datetime) -> str:
    """Millisecond-precision UTC ISO-8601 matching learnings_store's
    _iso_from_epoch/dwell_until_from_hours format (%Y-%m-%dT%H:%M:%S.mmmZ),
    which _parse_iso()/is_dwelling() require -- any other format silently
    fails closed to "not dwelling" (0.0 epoch sentinel)."""
    return dt_obj.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def _in_hours(hours: float) -> str:
    return _iso(datetime.now(timezone.utc) + timedelta(hours=hours))


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row) + "\n")


def _proposal_row(
    *, pid, kind, project, target_id=None, content=None, type_=None,
    confidence=8, status="pending", batch_id=None, posture=None, dwell_until=None,
) -> dict:
    row = {
        "id": pid,
        "kind": kind,
        "project": project,
        "target_id": target_id,
        "content": content,
        "type": type_,
        "confidence": confidence,
        "prevalence": {"sessions": 2, "agents": 1},
        "evidence": [{"session_id": "sess-test-1", "excerpt": "test evidence excerpt"}],
        "justification": "test justification",
        "fingerprint": f"fp-{pid}",
        "generated_at": _in_hours(-2),
        "status": status,
    }
    if batch_id is not None:
        row["batch_id"] = batch_id
    if posture is not None:
        row["posture"] = posture
    if dwell_until is not None:
        row["dwell_until"] = dwell_until
    return row


def _audit_record(
    *, proposal_id, kind, project, batch_id, outcome="applied",
    target_id=None, new_entry_id=None, posture=None,
) -> dict:
    rec = {
        "id": f"audit_{uuid.uuid4().hex[:12]}",
        "ts": _in_hours(-1),
        "proposal_id": proposal_id,
        "kind": kind,
        "project": project,
        "target_id": target_id,
        "method": "auto_apply",
        "reviewed_by": "optimistic-integrate",
        "ok": True,
        "outcome": outcome,
        "batch_id": batch_id,
    }
    if new_entry_id is not None:
        rec["new_entry_id"] = new_entry_id
    if posture is not None:
        rec["posture"] = posture
    return rec


class DailyReportTestBase(unittest.TestCase):
    def setUp(self) -> None:
        self.sandbox = Path(tempfile.mkdtemp(prefix="ccgm-daily-report-test-"))
        self.addCleanup(shutil.rmtree, self.sandbox, ignore_errors=True)

        self.dreaming_dir = self.sandbox / "dreaming"
        self.learnings_dir = self.sandbox / "learnings"
        self.home_dir = self.sandbox / "home"
        self.dreaming_dir.mkdir(parents=True)
        self.learnings_dir.mkdir(parents=True)
        self.home_dir.mkdir(parents=True)

        self.env = dict(os.environ)
        self.env["HOME"] = str(self.home_dir)
        self.env["CCGM_DREAMING_DIR"] = str(self.dreaming_dir)
        self.env["CCGM_LEARNINGS_DIR"] = str(self.learnings_dir)
        # Never let a real, ambient ANTHROPIC_API_KEY or autocommit setting
        # leak into these subprocesses -- irrelevant to digest rendering,
        # and autocommit specifically would fight the deliberate git-init
        # some tests perform directly on self.learnings_dir.
        self.env.pop("ANTHROPIC_API_KEY", None)
        self.env["CCGM_LEARNINGS_AUTOCOMMIT"] = "false"

    def _create_learning(self, *, project: str, content: str, confidence: int = 8) -> str:
        """Real `ccgm-learnings-log` subprocess -- creates a genuine store
        entry and returns its id. Used both for the entries a mocked add/
        supersede proposal "already created" and for a contradict's target."""
        proc = subprocess.run(
            [sys.executable, str(LEARNINGS_LOG),
             "--type", "pattern", "--content", content,
             "--confidence", str(confidence), "--project", project],
            env=self.env, capture_output=True, text=True, timeout=30, check=False,
        )
        self.assertEqual(proc.returncode, 0, msg=f"ccgm-learnings-log add failed: {proc.stderr}")
        return json.loads(proc.stdout.strip().splitlines()[-1])["id"]

    def _run_digest(self, date: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["bash", str(DREAM_DIGEST), date],
            env=self.env, capture_output=True, text=True, timeout=30, check=False,
        )

    def _digest_path(self, date: str) -> Path:
        return self.dreaming_dir / "digests" / f"{date}.md"

    def _surfaced_marker(self, batch_id: str) -> Path:
        return self.dreaming_dir / "state" / "surfaced" / f"{batch_id}.json"

    def _git(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["git", "-C", str(self.learnings_dir), *args],
            capture_output=True, text=True, timeout=30, check=False,
        )


class TwoAddsAndMidDwellContradictTest(DailyReportTestBase):
    """Plan.md Epic 5 test bullet 1: "A day with 2 auto-applied adds + 1
    mid-dwell contradict renders the section with action-items first and a
    correct headline; each row carries a valid undo command containing its
    id."
    """

    def test_renders_action_items_headline_and_per_row_undo(self) -> None:
        date = "2026-03-01"
        project = "proj-a"
        batch_id = "optbatch_test0001"

        # The contradict's target: a pre-existing store entry.
        contradict_target_content = "Old fact that is being contradicted."
        contradict_target_id = self._create_learning(
            project=project, content=contradict_target_content,
        )

        # The two "add" proposals' new entries -- in real operation Epic 3's
        # engine creates these via the SAME ccgm-learnings-log CLI when it
        # applies a pending learning_add proposal; this test creates them
        # directly to model that already-applied state.
        add1_content = "Fact one that was auto-integrated."
        add2_content = "Fact two that was auto-integrated."
        new_id_1 = self._create_learning(project=project, content=add1_content)
        new_id_2 = self._create_learning(project=project, content=add2_content)
        sha1 = _content_sha256(add1_content)
        sha2 = _content_sha256(add2_content)

        # Mixed batch: the 2 adds already graduated past their dwell window
        # (dwell_until in the past -> learnings_store.is_dwelling() == False,
        # i.e. "live") while the contradict is still inside its dwell window
        # (dwell_until in the future -> still "mid-dwell"). This is what
        # exercises BOTH "### Action items" (mid-dwell contradict) and
        # "### Routine confirmations" (live adds) in a single render --
        # plan.md Epic 5 test bullet 1's actual mixed-bucket intent.
        dwell_elapsed = _in_hours(-1)  # adds: dwell window already closed
        dwell_pending = _in_hours(24)  # contradict: clearly mid-dwell for the lifetime of this test

        proposals = [
            _proposal_row(
                pid="prop-add-1", kind="learning_add", project=project,
                content=add1_content, type_="pattern", status="auto_applied",
                batch_id=batch_id, posture="optimistic-dwell", dwell_until=dwell_elapsed,
            ),
            _proposal_row(
                pid="prop-add-2", kind="learning_add", project=project,
                content=add2_content, type_="pattern", status="auto_applied",
                batch_id=batch_id, posture="optimistic-dwell", dwell_until=dwell_elapsed,
            ),
            _proposal_row(
                pid="prop-contradict-1", kind="learning_contradict", project=project,
                target_id=contradict_target_id, status="auto_applied",
                batch_id=batch_id, posture="dwell-quarantine", dwell_until=dwell_pending,
            ),
        ]
        _write_jsonl(self.dreaming_dir / "proposals" / f"{date}.jsonl", proposals)

        audit_records = [
            _audit_record(
                proposal_id="prop-add-1", kind="learning_add", project=project,
                batch_id=batch_id, new_entry_id=new_id_1, posture="optimistic-dwell",
            ),
            _audit_record(
                proposal_id="prop-add-2", kind="learning_add", project=project,
                batch_id=batch_id, new_entry_id=new_id_2, posture="optimistic-dwell",
            ),
            _audit_record(
                proposal_id="prop-contradict-1", kind="learning_contradict", project=project,
                batch_id=batch_id, target_id=contradict_target_id, posture="dwell-quarantine",
            ),
        ]
        _write_jsonl(self.dreaming_dir / "state" / "apply-audit.jsonl", audit_records)

        # Real git history in the learnings store repo so the batch-revert
        # (blunt option) line resolves a concrete sha via `git log --grep`,
        # exactly the way the real optimistic engine's one commit-per-batch
        # (_suppressed_autocommit + _run_sync_commit) would leave it.
        init = self._git("init", "-q")
        self.assertEqual(init.returncode, 0, msg=init.stderr)
        self._git("config", "user.email", "test@example.invalid")
        self._git("config", "user.name", "Test")
        self._git("add", "-A")
        commit = self._git("commit", "-q", "-m", f"dreaming: optimistic-integrate batch {batch_id} ({date})")
        self.assertEqual(commit.returncode, 0, msg=commit.stderr)
        expected_sha = self._git("rev-parse", "HEAD").stdout.strip()
        self.assertTrue(expected_sha)

        proc = self._run_digest(date)
        self.assertEqual(proc.returncode, 0, msg=f"stdout={proc.stdout}\nstderr={proc.stderr}")

        body = self._digest_path(date).read_text(encoding="utf-8")

        self.assertIn("## Applied this run (auto)", body)
        # Only the contradict is still mid-dwell (the 2 adds already
        # graduated), so the headline's mid-dwell count is 1, not 3.
        self.assertIn("**3 auto-integrated, 1 mid-dwell, 0 flagged**", body)
        self.assertIn("### Action items", body)
        self.assertIn("### Routine confirmations", body)
        # Action items (mid-dwell contradict) must render before Routine
        # confirmations (live adds) -- the ordering plan.md Epic 5 bullet 1
        # exists to prove.
        self.assertLess(
            body.index("### Action items"),
            body.index("### Routine confirmations"),
            "Action items must render before Routine confirmations",
        )

        # Per-row undo commands, each containing the correct learnings-store id.
        self.assertIn(
            f"ccgm-learnings-log deprecate {new_id_1} --project {project} --expected-sha {sha1}",
            body,
        )
        self.assertIn(
            f"ccgm-learnings-log deprecate {new_id_2} --project {project} --expected-sha {sha2}",
            body,
        )
        self.assertIn(
            f"ccgm-learnings-log verify {contradict_target_id} --project {project}",
            body,
        )

        # Batch-revert (blunt) line resolves the real commit sha.
        self.assertIn(f"git -C {self.learnings_dir} revert {expected_sha}", body)

        # Surfaced marker was written for this batch.
        marker = self._surfaced_marker(batch_id)
        self.assertTrue(marker.is_file())
        marker_data = json.loads(marker.read_text(encoding="utf-8"))
        self.assertEqual(marker_data["batch_id"], batch_id)
        self.assertEqual(marker_data["row_count"], 3)


class ZeroAutoAppliedTest(DailyReportTestBase):
    """Plan.md Epic 5 test bullet 2: "A day with zero auto-applied rows
    renders no 'Applied last night' section." (Section is silent, not
    empty -- no heading at all.)
    """

    def test_no_auto_applied_rows_renders_no_section(self) -> None:
        date = "2026-03-02"
        proposals = [
            _proposal_row(
                pid="prop-pending-1", kind="learning_add", project="proj-b",
                content="Some pending fact.", type_="pattern", status="pending",
            ),
        ]
        _write_jsonl(self.dreaming_dir / "proposals" / f"{date}.jsonl", proposals)

        proc = self._run_digest(date)
        self.assertEqual(proc.returncode, 0, msg=f"stdout={proc.stdout}\nstderr={proc.stderr}")

        body = self._digest_path(date).read_text(encoding="utf-8")
        self.assertNotIn("## Applied this run (auto)", body)

        # No proposals were ever auto-applied -- no surfaced-marker directory
        # should even be created.
        self.assertFalse((self.dreaming_dir / "state" / "surfaced").exists())

    def test_empty_proposals_file_renders_no_section(self) -> None:
        date = "2026-03-03"
        (self.dreaming_dir / "proposals").mkdir(parents=True, exist_ok=True)
        (self.dreaming_dir / "proposals" / f"{date}.jsonl").write_text("", encoding="utf-8")

        proc = self._run_digest(date)
        self.assertEqual(proc.returncode, 0, msg=f"stdout={proc.stdout}\nstderr={proc.stderr}")

        body = self._digest_path(date).read_text(encoding="utf-8")
        self.assertNotIn("## Applied this run (auto)", body)


class IdempotentAndSurfacedDedupTest(DailyReportTestBase):
    """Plan.md Epic 5 test bullet 3: "Re-running the report for the same
    day is idempotent; a batch already surfaced is not re-rendered on a
    later day."
    """

    def _seed_single_add_batch(self, *, date: str, batch_id: str, project: str) -> None:
        content = "A single auto-integrated fact."
        new_id = self._create_learning(project=project, content=content)
        proposals = [
            _proposal_row(
                pid=f"prop-{batch_id}", kind="learning_add", project=project,
                content=content, type_="pattern", status="auto_applied",
                batch_id=batch_id, posture="optimistic-dwell", dwell_until=_in_hours(24),
            ),
        ]
        _write_jsonl(self.dreaming_dir / "proposals" / f"{date}.jsonl", proposals)
        audit_records = [
            _audit_record(
                proposal_id=f"prop-{batch_id}", kind="learning_add", project=project,
                batch_id=batch_id, new_entry_id=new_id, posture="optimistic-dwell",
            ),
        ]
        _write_jsonl(self.dreaming_dir / "state" / "apply-audit.jsonl", audit_records)

    def test_rerendering_same_day_is_idempotent(self) -> None:
        date = "2026-03-04"
        batch_id = "optbatch_test0002"
        self._seed_single_add_batch(date=date, batch_id=batch_id, project="proj-c")

        first = self._run_digest(date)
        self.assertEqual(first.returncode, 0, msg=first.stderr)
        first_body = self._digest_path(date).read_text(encoding="utf-8")
        self.assertIn("## Applied this run (auto)", first_body)
        self.assertTrue(self._surfaced_marker(batch_id).is_file())

        # Second render of the SAME day: the batch was already surfaced by
        # the first render, so the section is now silent (never shown twice).
        second = self._run_digest(date)
        self.assertEqual(second.returncode, 0, msg=second.stderr)
        second_body = self._digest_path(date).read_text(encoding="utf-8")
        self.assertNotIn("## Applied this run (auto)", second_body)

        # Third render converges to the SAME (now-stable) output as the
        # second -- the fixed point IS the idempotency guarantee: once
        # surfaced, further re-renders never mutate the surfaced state or
        # the digest content again.
        third = self._run_digest(date)
        self.assertEqual(third.returncode, 0, msg=third.stderr)
        third_body = self._digest_path(date).read_text(encoding="utf-8")
        self.assertEqual(second_body, third_body)

    def test_batch_already_surfaced_is_not_rerendered_on_a_later_day(self) -> None:
        day1 = "2026-03-05"
        day2 = "2026-03-06"
        batch_id = "optbatch_test0003"
        project = "proj-d"
        self._seed_single_add_batch(date=day1, batch_id=batch_id, project=project)

        first = self._run_digest(day1)
        self.assertEqual(first.returncode, 0, msg=first.stderr)
        self.assertIn("## Applied this run (auto)", self._digest_path(day1).read_text(encoding="utf-8"))
        self.assertTrue(self._surfaced_marker(batch_id).is_file())

        # Defensively, day2's OWN proposals file references the SAME
        # batch_id (this should never happen in real nightly operation --
        # each day's batch is created into that day's own file -- but the
        # marker mechanism is the sole dedup axis and must hold regardless
        # of how a stale/duplicated batch_id would arrive).
        self._seed_single_add_batch(date=day2, batch_id=batch_id, project=project)

        second = self._run_digest(day2)
        self.assertEqual(second.returncode, 0, msg=second.stderr)
        day2_body = self._digest_path(day2).read_text(encoding="utf-8")
        self.assertNotIn("## Applied this run (auto)", day2_body)


if __name__ == "__main__":
    unittest.main()
