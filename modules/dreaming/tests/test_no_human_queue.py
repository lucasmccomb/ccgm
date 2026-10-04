#!/usr/bin/env python3
"""
No human queue (#1098 item 2.3) and subagent corroboration.

Every proposal the active pipeline touches ends integrated or discarded with
a reason; nothing parks for a person. With optimistic integration off (or in
shadow) nothing is discarded: off means hold everything, change nothing.

* run_optimistic_integrate() turns every content decision (floor, prevalence,
  cap, anomaly, compaction guard, malformed row, a permanent apply failure)
  into status `discarded` plus a `discarded` audit record naming the reason.
  Infra hiccups (internal_error, CAS exhaustion) stay pending for the next
  night and the expiry sweep.
* `_global` adds promote automatically when transcript-verified breadth holds
  (promotion_min_sessions sessions over promotion_min_slugs slugs); otherwise
  they are rescoped to the slug their evidence comes from.
* expire_pending() discards pending rows older than pending_max_age_hours
  (default 48), plain and gzipped, in active mode only.
* retention_check() lets the retention step delete an aged proposals file only
  after auditing its pending rows as expired, and only in active mode.
* The dream-daily chain drives all of it.

All transcripts are synthetic. CCGM_LEARNINGS_DIR, CCGM_DREAMING_DIR,
CCGM_CLAUDE_PROJECTS_DIR and HOME point at temp dirs before import.

Run with: python3 -m pytest modules/dreaming/tests/test_no_human_queue.py -q
"""

from __future__ import annotations

import gzip
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
MODULE = HERE.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(MODULE / "lib"))

for _name in ("learnings_store", "dream_analyze", "apply_dream_proposal", "transcript_miner"):
    sys.modules.pop(_name, None)

_TMP_LEARNINGS = tempfile.mkdtemp(prefix="ccgm-nhq-learnings-")
_TMP_DREAMING = tempfile.mkdtemp(prefix="ccgm-nhq-dreaming-")
_TMP_PROJECTS = tempfile.mkdtemp(prefix="ccgm-nhq-projects-")
_TMP_HOME = tempfile.mkdtemp(prefix="ccgm-nhq-home-")
_ORIG = {k: os.environ.get(k) for k in ("CCGM_LEARNINGS_DIR", "CCGM_DREAMING_DIR", "CCGM_CLAUDE_PROJECTS_DIR", "HOME")}
os.environ["CCGM_LEARNINGS_DIR"] = _TMP_LEARNINGS
os.environ["CCGM_DREAMING_DIR"] = _TMP_DREAMING
os.environ["CCGM_CLAUDE_PROJECTS_DIR"] = _TMP_PROJECTS
os.environ["HOME"] = _TMP_HOME

import apply_dream_proposal as adp  # noqa: E402
import dream_analyze as da  # noqa: E402
import eligibility as elig  # noqa: E402
import learnings_store as ls  # noqa: E402
import transcript_fixtures as tf  # noqa: E402

DAILY = MODULE / "bin" / "dream-daily.sh"

SENTENCE = (
    "The Edit tool does not follow symlinks so read the workspace path first "
    "before editing the file"
)


def tearDownModule() -> None:
    for key, orig in _ORIG.items():
        if orig is not None:
            os.environ[key] = orig
        else:
            os.environ.pop(key, None)


def _iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%S.000Z")


def _hours_ago(h: float) -> str:
    return _iso(datetime.now(timezone.utc) - timedelta(hours=h))


def _uid(label: str) -> str:
    return f"{label}-{uuid.uuid4().hex[:8]}"


def _row(*, pid: str, kind: str, project: str, target_id=None, content=None, type_=None,
         confidence: int = 9, sessions: int = 3, evidence=None, generated_at=None, **extra) -> dict:
    row = {
        "id": pid, "kind": kind, "project": project, "target_id": target_id,
        "content": content, "type": type_, "confidence": confidence,
        "prevalence": {"sessions": sessions, "agents": 1},
        "evidence": evidence or [{"session_id": f"sess-{pid}", "excerpt": "example"}],
        "justification": "no-human-queue test", "fingerprint": f"fp-{pid}",
        "generated_at": generated_at or _hours_ago(1), "status": "pending",
    }
    row.update(extra)
    return row


class Base(unittest.TestCase):
    def setUp(self) -> None:
        for key, value in (
            ("CCGM_LEARNINGS_DIR", str(ls.LEARNINGS_ROOT)), ("CCGM_DREAMING_DIR", _TMP_DREAMING),
            ("CCGM_CLAUDE_PROJECTS_DIR", str(ls.CLAUDE_PROJECTS_ROOT)), ("HOME", _TMP_HOME),
        ):
            self._pin(key, value)
        adp.proposals_dir().mkdir(parents=True, exist_ok=True)
        adp._write_optimistic_state_atomic(adp._default_optimistic_state())
        self._write_config({"enabled": True})

    def _pin(self, key: str, value: str) -> None:
        had, prior = key in os.environ, os.environ.get(key)
        os.environ[key] = value
        self.addCleanup(lambda: os.environ.__setitem__(key, prior) if had else os.environ.pop(key, None))

    def _write_config(self, optimistic: dict, **top) -> None:
        p = da.dreaming_dir() / "config.json"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps({**top, "optimistic_integration": optimistic}), encoding="utf-8")

    def _day(self) -> str:
        return f"2026-test-{uuid.uuid4().hex[:8]}"

    def _write_file(self, name: str, rows: list, *, gz: bool = False) -> Path:
        text = "".join(json.dumps(r, sort_keys=True) + "\n" for r in rows)
        path = adp.proposals_dir() / (f"{name}.jsonl.gz" if gz else f"{name}.jsonl")
        if gz:
            with gzip.open(path, "wt", encoding="utf-8") as fh:
                fh.write(text)
        else:
            path.write_text(text, encoding="utf-8")
        return path

    def _rows(self, path: Path) -> dict:
        opener = gzip.open if str(path).endswith(".gz") else open
        with opener(path, "rt", encoding="utf-8") as fh:
            return {r["id"]: r for r in (json.loads(ln) for ln in fh if ln.strip())}

    def _audit(self) -> list:
        path = adp.apply_audit_path()
        if not path.is_file():
            return []
        return [json.loads(ln) for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]

    def _discard_record(self, pid: str) -> dict | None:
        found = None
        for rec in self._audit():
            if rec.get("outcome") == "discarded" and rec.get("proposal_id") == pid:
                found = rec
        return found

    def _assert_discarded(self, path: Path, pid: str, reason: str) -> None:
        row = self._rows(path)[pid]
        self.assertEqual(row["status"], "discarded", row)
        self.assertEqual(row["discard_reason"], reason, row)
        self.assertIn("discarded_at", row)
        rec = self._discard_record(pid)
        self.assertIsNotNone(rec, f"no discarded audit record for {pid}")
        self.assertEqual(rec["reason"], reason)
        self.assertNotIn("ok", rec, "a discard must never be counted as an apply")

    def _seed(self, slug: str, content: str = "seed learning") -> str:
        e = ls.build_entry(type_="pattern", content=content, confidence=8)
        e["project"] = slug
        ls.append_entry(e, slug=slug)
        return e["id"]

    def _session(self, sid: str, *, slug: str, turns=None, subagent_turns=None) -> Path:
        project = ls.CLAUDE_PROJECTS_ROOT / f"proj-{uuid.uuid4().hex[:6]}"
        cwd = f"/synthetic-nonexistent/code/{slug}"
        base = tf.iso(datetime.now(timezone.utc) - timedelta(hours=6))
        path = tf.write_transcript(project / f"{sid}.jsonl", turns or [tf.user_turn(SENTENCE, human=True)],
                                   session_id=sid, cwd=cwd, base_ts=base)
        if subagent_turns is not None:
            tf.write_transcript(project / sid / "subagents" / "agent-x.jsonl", subagent_turns,
                                session_id=sid, cwd=cwd, base_ts=base)
        return path


# ---------------------------------------------------------------------------
# Every engine decision reaches a terminal state.
# ---------------------------------------------------------------------------


class EngineDiscardTests(Base):
    def test_below_floor_is_discarded_low_confidence(self):
        slug, day = _uid("floor"), self._day()
        path = self._write_file(day, [_row(pid=_uid("lo"), kind="learning_add", project=slug,
                                           content="weak", type_="pattern", confidence=5)])
        pid = next(iter(self._rows(path)))
        adp.run_optimistic_integrate(day)
        self._assert_discarded(path, pid, "low_confidence")

    def test_low_prevalence_add_is_discarded(self):
        slug, day = _uid("prev"), self._day()
        pid = _uid("lp")
        path = self._write_file(day, [_row(pid=pid, kind="learning_add", project=slug,
                                           content="one session only", type_="pattern", sessions=1)])
        adp.run_optimistic_integrate(day)
        self._assert_discarded(path, pid, "low_prevalence")

    def test_over_cap_rows_are_discarded_cap_exceeded(self):
        self._write_config({"enabled": True, "max_add_supersede_per_run": 1})
        slug, day = _uid("cap"), self._day()
        pids = [_uid(f"c{i}") for i in range(3)]
        path = self._write_file(day, [_row(pid=p, kind="learning_add", project=slug, content=f"content {i}",
                                           type_="pattern") for i, p in enumerate(pids)])
        summary = adp.run_optimistic_integrate(day)
        self.assertEqual(summary["applied"], 1, summary)
        statuses = [self._rows(path)[p]["status"] for p in pids]
        self.assertEqual(statuses.count("auto_applied"), 1)
        for p in pids:
            if self._rows(path)[p]["status"] != "auto_applied":
                self._assert_discarded(path, p, "cap_exceeded")

    def test_compaction_guard_failure_is_discarded(self):
        slug, day = _uid("cg"), self._day()
        target = self._seed(slug, "Use port 5432 for the db")
        pid = _uid("sup")
        path = self._write_file(day, [_row(pid=pid, kind="learning_supersede", project=slug, target_id=target,
                                           content="use the db port", type_="pattern",
                                           compaction_guard_failed={"dropped_tokens": ["5432"]})])
        adp.run_optimistic_integrate(day)
        self._assert_discarded(path, pid, "compaction_guard_failed")

    def test_malformed_project_is_discarded(self):
        day = self._day()
        pid = _uid("bad")
        row = _row(pid=pid, kind="learning_add", project="x", content="x", type_="pattern")
        row["project"] = None
        path = self._write_file(day, [row])
        adp.run_optimistic_integrate(day)
        self._assert_discarded(path, pid, "malformed")

    def test_dead_target_is_discarded_target_gone(self):
        slug, day = _uid("gone"), self._day()
        self._seed(slug)
        pid = _uid("v")
        path = self._write_file(day, [_row(pid=pid, kind="learning_verify", project=slug,
                                           target_id="does-not-exist")])
        adp.run_optimistic_integrate(day)
        self._assert_discarded(path, pid, "target_gone")

    def test_eviction_concentration_discards_the_withheld_evictions(self):
        slug, day = _uid("conc"), self._day()
        target = self._seed(slug)
        pids = [_uid(f"d{i}") for i in range(2)]
        path = self._write_file(day, [_row(pid=p, kind="learning_contradict", project=slug, target_id=target)
                                      for p in pids])
        adp.run_optimistic_integrate(day)
        for p in pids:
            self._assert_discarded(path, p, "batch_anomaly")

    def test_suspended_breaker_holds_rows_for_the_expiry_sweep(self):
        adp._write_optimistic_state_atomic({**adp._default_optimistic_state(), "suspended": True,
                                            "suspended_at": _hours_ago(1)})
        slug, day = _uid("susp"), self._day()
        pid = _uid("a")
        path = self._write_file(day, [_row(pid=pid, kind="learning_add", project=slug, content="x",
                                           type_="pattern")])
        adp.run_optimistic_integrate(day)
        self.assertEqual(self._rows(path)[pid]["status"], "pending")

    def test_applied_rows_carry_content_in_the_audit(self):
        slug, day = _uid("aud"), self._day()
        pid = _uid("a")
        self._write_file(day, [_row(pid=pid, kind="learning_add", project=slug,
                                    content="Run the formatter before committing", type_="pattern")])
        adp.run_optimistic_integrate(day)
        rec = next(r for r in self._audit() if r.get("proposal_id") == pid and r.get("outcome") == "applied")
        self.assertEqual(rec["content"], "Run the formatter before committing")

    def test_discarded_and_rescoped_rows_satisfy_the_proposal_schema(self):
        schema = da._load_proposal_schema()
        slug, day = _uid("schema"), self._day()
        pid = _uid("lo")
        path = self._write_file(day, [_row(pid=pid, kind="learning_add", project=slug, content="weak",
                                           type_="pattern", confidence=3, trigger=None, novelty=None)])
        adp.run_optimistic_integrate(day)
        row = self._rows(path)[pid]
        row["rescoped_from"] = ls.GLOBAL_SLUG
        self.assertEqual(da.validate_against_schema(row, schema), [])
        self.assertIn("discarded", schema["properties"]["status"]["enum"])
        for field in ("discard_reason", "discard_detail", "discarded_at", "rescoped_from"):
            self.assertIn(field, schema["properties"], field)

    def test_shadow_discards_nothing(self):
        self._write_config({"enabled": "shadow"})
        slug, day = _uid("shadow"), self._day()
        pid = _uid("lo")
        path = self._write_file(day, [_row(pid=pid, kind="learning_add", project=slug, content="weak",
                                           type_="pattern", confidence=3)])
        adp.run_optimistic_integrate(day, shadow=True)
        self.assertEqual(self._rows(path)[pid]["status"], "pending")
        self.assertIsNone(self._discard_record(pid))


class CarryOverTests(Base):
    def test_yesterdays_pending_rows_are_decided_tonight(self):
        today = datetime.now(timezone.utc).date()
        # Real dates, far in the future so no other test's files collide.
        tonight = (today + timedelta(days=4000 + uuid.uuid4().int % 1000)).isoformat()
        yesterday = (datetime.fromisoformat(tonight) - timedelta(days=1)).date().isoformat()
        slug = _uid("carry")
        y_pid, t_pid = _uid("y"), _uid("t")
        y_path = self._write_file(yesterday, [_row(pid=y_pid, kind="learning_add", project=slug,
                                                   content="from a paused night", type_="pattern")])
        self._write_file(tonight, [_row(pid=t_pid, kind="learning_add", project=slug,
                                        content="from tonight", type_="pattern")])
        summary = adp.run_optimistic_integrate(tonight)
        self.assertEqual(summary["applied"], 2, summary)
        self.assertEqual(self._rows(y_path)[y_pid]["status"], "auto_applied")


# ---------------------------------------------------------------------------
# _global: automatic with breadth, otherwise project-scoped.
# ---------------------------------------------------------------------------


class GlobalScopeTests(Base):
    def _evidence(self, sessions):
        return [{"session_id": s, "excerpt": SENTENCE} for s in sessions]

    def test_breadth_holds_promotes_to_global_with_dwell(self):
        a, b = _uid("ga"), _uid("gb")
        sids = [_uid("s1"), _uid("s2"), _uid("s3")]
        self._session(sids[0], slug=a)
        self._session(sids[1], slug=a)
        self._session(sids[2], slug=b)
        day, pid = self._day(), _uid("g")
        content = f"Read the workspace path before editing {uuid.uuid4().hex[:6]}"
        path = self._write_file(day, [_row(pid=pid, kind="learning_add", project=ls.GLOBAL_SLUG, content=content,
                                           type_="pitfall", evidence=self._evidence(sids))])
        summary = adp.run_optimistic_integrate(day)
        self.assertEqual(summary["applied"], 1, summary)
        row = self._rows(path)[pid]
        self.assertEqual(row["status"], "auto_applied")
        self.assertEqual(row["project"], ls.GLOBAL_SLUG)
        head = next(h for h in ls.load_all(ls.GLOBAL_SLUG) if h.get("content") == content)
        self.assertIsNotNone(head.get("dwell_until"))

    def test_one_slug_of_evidence_rescopes_to_that_project(self):
        a = _uid("solo")
        sids = [_uid("s1"), _uid("s2"), _uid("s3")]
        for s in sids:
            self._session(s, slug=a)
        day, pid = self._day(), _uid("g")
        path = self._write_file(day, [_row(pid=pid, kind="learning_add", project=ls.GLOBAL_SLUG,
                                           content="Read the workspace path first", type_="pitfall",
                                           evidence=self._evidence(sids))])
        summary = adp.run_optimistic_integrate(day)
        self.assertEqual(summary["applied"], 1, summary)
        row = self._rows(path)[pid]
        self.assertEqual(row["status"], "auto_applied")
        self.assertEqual(row["project"], a)
        self.assertEqual(row["rescoped_from"], ls.GLOBAL_SLUG)
        self.assertEqual(row["prevalence"]["sessions"], 3)
        self.assertTrue(any(h.get("content") == "Read the workspace path first" for h in ls.load_all(a)))

    def test_unverifiable_global_add_is_discarded_failed_corroboration(self):
        day, pid = self._day(), _uid("g")
        path = self._write_file(day, [_row(pid=pid, kind="learning_add", project=ls.GLOBAL_SLUG,
                                           content="no transcript backs this", type_="pattern")])
        adp.run_optimistic_integrate(day)
        self._assert_discarded(path, pid, "failed_corroboration")

    def test_global_verify_is_discarded_manual_only(self):
        day, pid = self._day(), _uid("gv")
        path = self._write_file(day, [_row(pid=pid, kind="learning_verify", project=ls.GLOBAL_SLUG,
                                           target_id="some-global-row")])
        adp.run_optimistic_integrate(day)
        self._assert_discarded(path, pid, "global_manual_only")


# ---------------------------------------------------------------------------
# Expiry sweep and retention: active only.
# ---------------------------------------------------------------------------


class ExpiryTests(Base):
    def _fixture(self):
        name_old, name_gz = self._day(), self._day()
        old_pid, fresh_pid, gz_pid, done_pid = _uid("old"), _uid("fresh"), _uid("gz"), _uid("done")
        plain = self._write_file(name_old, [
            _row(pid=old_pid, kind="learning_add", project="p", content="x", type_="pattern",
                 generated_at=_hours_ago(60)),
            _row(pid=fresh_pid, kind="learning_add", project="p", content="y", type_="pattern",
                 generated_at=_hours_ago(10)),
            {**_row(pid=done_pid, kind="learning_add", project="p", content="z", type_="pattern",
                    generated_at=_hours_ago(90)), "status": "auto_applied"},
        ])
        gz = self._write_file(name_gz, [_row(pid=gz_pid, kind="learning_verify", project="p", target_id="t",
                                             generated_at=_hours_ago(24 * 40))], gz=True)
        return plain, gz, old_pid, fresh_pid, gz_pid, done_pid

    def test_active_expires_rows_older_than_48h_plain_and_gz(self):
        plain, gz, old_pid, fresh_pid, gz_pid, done_pid = self._fixture()
        result = adp.expire_pending()
        self.assertGreaterEqual(result["expired"], 2, result)
        self._assert_discarded(plain, old_pid, "expired")
        self._assert_discarded(gz, gz_pid, "expired")
        self.assertEqual(self._rows(plain)[fresh_pid]["status"], "pending")
        self.assertEqual(self._rows(plain)[done_pid]["status"], "auto_applied")

    def test_max_age_is_configurable(self):
        self._write_config({"enabled": True, "pending_max_age_hours": 6})
        plain, _gz, _old, fresh_pid, _g, _d = self._fixture()
        adp.expire_pending()
        self._assert_discarded(plain, fresh_pid, "expired")

    def test_off_holds_everything(self):
        self._write_config({"enabled": False})
        plain, gz, old_pid, _f, gz_pid, _d = self._fixture()
        result = adp.expire_pending()
        self.assertEqual(result["outcome"], "held")
        self.assertEqual(self._rows(plain)[old_pid]["status"], "pending")
        self.assertEqual(self._rows(gz)[gz_pid]["status"], "pending")
        self.assertIsNone(self._discard_record(old_pid))

    def test_shadow_holds_everything(self):
        self._write_config({"enabled": "shadow"})
        plain, _gz, old_pid, _f, _g, _d = self._fixture()
        self.assertEqual(adp.expire_pending()["outcome"], "held")
        self.assertEqual(self._rows(plain)[old_pid]["status"], "pending")

    def test_legacy_flag_alone_is_not_active(self):
        # The nightly gate reads the on-disk flag only; a legacy
        # auto_apply_counters=true config never activates discarding.
        p = da.dreaming_dir() / "config.json"
        p.write_text(json.dumps({"auto_apply_counters": True}), encoding="utf-8")
        plain, _gz, old_pid, _f, _g, _d = self._fixture()
        self.assertEqual(adp.expire_pending()["outcome"], "held")
        self.assertEqual(self._rows(plain)[old_pid]["status"], "pending")


class RetentionCheckTests(Base):
    def test_active_audits_pending_rows_expired_then_allows_delete(self):
        pid = _uid("r")
        gz = self._write_file(self._day(), [_row(pid=pid, kind="learning_add", project="p", content="x",
                                                 type_="pattern", generated_at=_hours_ago(24 * 70))], gz=True)
        result = adp.retention_check(gz)
        self.assertEqual((result["delete"], result["expired"]), (True, 1), result)
        rec = self._discard_record(pid)
        self.assertEqual(rec["reason"], "expired")
        self.assertEqual(rec["method"], "retention")

    def test_off_refuses_to_delete_a_file_with_pending_rows(self):
        self._write_config({"enabled": False})
        pid = _uid("r")
        gz = self._write_file(self._day(), [_row(pid=pid, kind="learning_add", project="p", content="x",
                                                 type_="pattern")], gz=True)
        result = adp.retention_check(gz)
        self.assertEqual((result["delete"], result["held"]), (False, 1), result)
        self.assertIsNone(self._discard_record(pid))

    def test_file_without_pending_rows_is_deletable_in_any_mode(self):
        self._write_config({"enabled": False})
        gz = self._write_file(self._day(), [{**_row(pid=_uid("r"), kind="learning_add", project="p",
                                                    content="x", type_="pattern"), "status": "accepted"}], gz=True)
        self.assertTrue(adp.retention_check(gz)["delete"])


# ---------------------------------------------------------------------------
# Subagent corroboration (follow-up from #1114).
# ---------------------------------------------------------------------------


class SubagentCorroborationTests(Base):
    def test_excerpt_only_in_a_subagent_file_corroborates(self):
        slug, sid = _uid("sub"), _uid("sess")
        quote = "the migration needs the reserved word order quoted in every index definition"
        self._session(sid, slug=slug, turns=[tf.user_turn("please run the unit", human=True)],
                      subagent_turns=[tf.assistant_turn(quote)])
        cfg = elig.default_eligibility()
        sv = adp._build_session_verification(sid, cfg)
        self.assertTrue(sv.resolved)
        self.assertTrue(adp._excerpt_corroborated(quote, sv, cfg))

    def test_excerpt_in_neither_file_does_not_corroborate(self):
        slug, sid = _uid("sub"), _uid("sess")
        self._session(sid, slug=slug, turns=[tf.user_turn("please run the unit", human=True)],
                      subagent_turns=[tf.assistant_turn("nothing relevant was said in this subagent run")])
        cfg = elig.default_eligibility()
        sv = adp._build_session_verification(sid, cfg)
        self.assertFalse(adp._excerpt_corroborated(
            "the migration needs the reserved word order quoted in every index definition", sv, cfg))

    def test_oversized_session_streams_the_subagent_files_too(self):
        slug, sid = _uid("sub"), _uid("sess")
        quote = "always pass the clone ports from the env clone file when starting the dev server"
        self._session(sid, slug=slug, turns=[tf.user_turn("x " * 50, human=True)],
                      subagent_turns=[tf.assistant_turn(quote)])
        cfg = {**elig.default_eligibility(), "max_transcript_bytes": 10}
        sv = adp._build_session_verification(sid, cfg)
        self.assertTrue(sv.oversized)
        self.assertTrue(adp._excerpt_corroborated(quote, sv, cfg))

    def test_subagent_evidence_counts_as_a_verified_session(self):
        slug = _uid("sub")
        sids = [_uid("s1"), _uid("s2")]
        quote = "the migration needs the reserved word order quoted in every index definition"
        for s in sids:
            self._session(s, slug=slug, turns=[tf.user_turn("go", human=True)],
                          subagent_turns=[tf.assistant_turn(quote)])
        row = _row(pid=_uid("a"), kind="learning_add", project=slug, content=quote, type_="pitfall",
                   evidence=[{"session_id": s, "excerpt": quote} for s in sids])
        _bundle, ctx = adp.gather_eligibility_signals(row, slug=slug, cache={}, heads={},
                                                      elig_cfg=elig.default_eligibility())
        self.assertEqual(sorted(ctx["verified_session_ids"]), sorted(sids))


class EvalRefreshReasonTests(Base):
    def test_disabled_reason_names_the_flag_and_the_weekly_smoke(self):
        ok, reason = adp._eval_refresh_preconditions("2026-10-04", da.load_config())
        self.assertFalse(ok)
        self.assertEqual(
            reason,
            "eval_refresh_enabled is false; set optimistic_integration.eval_refresh_enabled=true "
            "to run the weekly regression smoke (~$1.50)",
        )


# ---------------------------------------------------------------------------
# The nightly chain end to end (acceptance).
# ---------------------------------------------------------------------------


def _stub(bin_dir: Path, name: str, body: str) -> None:
    bin_dir.mkdir(parents=True, exist_ok=True)
    (bin_dir / name).write_text(f"#!/usr/bin/env bash\n{body}\n", encoding="utf-8")


class NightlyChainTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="ccgm-nhq-chain-"))
        self.root = self.tmp / "dreaming"
        self.pdir = self.root / "proposals"
        self.pdir.mkdir(parents=True)
        self.bins = self.tmp / "bin"
        _stub(self.bins, "dream-analyze.sh", "exit 0")
        self.gate = self.tmp / "gate.sh"
        self.gate.write_text('#!/usr/bin/env bash\necho \'{"gate": "open", "code": "ok", "reason": "ok", "since": null}\'\nexit 0\n',
                             encoding="utf-8")
        self.today = datetime.now(timezone.utc).date()
        self.env = {
            **os.environ, "CCGM_DREAMING_DIR": str(self.root), "CCGM_DREAMING_BIN_DIR": str(self.bins),
            "CCGM_DREAMING_LOGS_DIR": str(self.tmp / "logs"), "CCGM_DREAMING_TODAY": self.today.isoformat(),
            "CCGM_LEARNINGS_DIR": str(self.tmp / "learnings"), "CCGM_CLAUDE_PROJECTS_DIR": str(self.tmp / "projects"),
            "HOME": str(self.tmp / "home"), "CCGM_DREAMING_EVAL_SCRIPT": str(self.gate),
        }
        (self.tmp / "home").mkdir()

    def _config(self, enabled) -> None:
        (self.root / "config.json").write_text(json.dumps({"enabled": True, "optimistic_integration": {"enabled": enabled}}),
                                               encoding="utf-8")

    def _file(self, day: str, rows: list, *, gz: bool = False, age_days: float | None = None) -> Path:
        text = "".join(json.dumps(r) + "\n" for r in rows)
        path = self.pdir / (f"{day}.jsonl.gz" if gz else f"{day}.jsonl")
        if gz:
            with gzip.open(path, "wt", encoding="utf-8") as fh:
                fh.write(text)
        else:
            path.write_text(text, encoding="utf-8")
        if age_days is not None:
            t = time.time() - age_days * 86400
            os.utime(path, (t, t))
        return path

    def _seed_fixture(self) -> dict:
        d = lambda n: (self.today - timedelta(days=n)).isoformat()  # noqa: E731
        tonight = [
            _row(pid="t-add", kind="learning_add", project="widget", content="Run the formatter first", type_="pattern"),
            _row(pid="t-low", kind="learning_add", project="widget", content="weak idea", type_="pattern", confidence=4),
            _row(pid="t-gv", kind="learning_verify", project=ls.GLOBAL_SLUG, target_id="g1"),
        ]
        return {
            "tonight": self._file(d(0), tonight),
            "old": self._file(d(3), [_row(pid="o-1", kind="learning_add", project="widget", content="old",
                                          type_="pattern", generated_at=_hours_ago(72))]),
            "gz": self._file(d(40), [_row(pid="z-1", kind="learning_add", project="widget", content="older",
                                          type_="pattern", generated_at=_hours_ago(24 * 40))], gz=True, age_days=40),
            "ancient": self._file(d(70), [_row(pid="a-1", kind="learning_add", project="widget", content="ancient",
                                               type_="pattern", generated_at=_hours_ago(24 * 70))], gz=True, age_days=70),
        }

    def _run(self):
        return subprocess.run(["bash", str(DAILY)], capture_output=True, text=True, env=self.env, timeout=300)

    def _all_rows(self) -> list:
        rows = []
        for path in sorted(self.pdir.iterdir()):
            opener = gzip.open if path.name.endswith(".gz") else open
            with opener(path, "rt", encoding="utf-8") as fh:
                rows.extend(json.loads(ln) for ln in fh if ln.strip())
        return rows

    def _audit(self) -> list:
        path = self.root / "state" / "apply-audit.jsonl"
        if not path.is_file():
            return []
        return [json.loads(ln) for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]

    def test_active_night_leaves_nothing_pending_past_48h_and_every_row_has_a_reason(self):
        self._config(True)
        files = self._seed_fixture()
        proc = self._run()
        self.assertEqual(proc.returncode, 0, proc.stderr)
        cutoff = datetime.now(timezone.utc) - timedelta(hours=48)
        for row in self._all_rows():
            if row["status"] == "pending":
                self.assertGreater(ls._parse_iso(row["generated_at"]), cutoff.timestamp(), row)
        tonight = {r["id"]: r for r in self._all_rows() if r["id"].startswith("t-")}
        self.assertEqual({k: v["status"] for k, v in tonight.items()},
                         {"t-add": "auto_applied", "t-low": "discarded", "t-gv": "discarded"})
        audit = self._audit()
        for pid in ("t-add", "t-low", "t-gv", "o-1", "z-1", "a-1"):
            recs = [r for r in audit if r.get("proposal_id") == pid and r.get("outcome") in ("applied", "discarded")]
            self.assertTrue(recs, f"no terminal audit record for {pid}")
            for r in recs:
                if r["outcome"] == "discarded":
                    self.assertTrue(r.get("reason"), r)
        reasons = {r["proposal_id"]: r["reason"] for r in audit if r.get("outcome") == "discarded"}
        self.assertEqual(reasons["t-low"], "low_confidence")
        self.assertEqual(reasons["o-1"], "expired")
        self.assertEqual(reasons["a-1"], "expired")
        self.assertFalse(files["ancient"].exists(), "retention deletes the aged file once its rows are audited")
        health = json.loads((self.root / "state" / "health.json").read_text())
        self.assertGreaterEqual(health["expired_last_night"], 2)

    def test_off_night_discards_nothing_and_keeps_files_with_pending_rows(self):
        self._config(False)
        files = self._seed_fixture()
        before = {r["id"]: r["status"] for r in self._all_rows()}
        proc = self._run()
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertTrue(files["ancient"].exists(), "off mode must never delete pending proposals")
        after = {r["id"]: r["status"] for r in self._all_rows()}
        self.assertEqual(after, before)
        self.assertFalse([r for r in self._audit() if r.get("outcome") == "discarded"])

    def test_off_night_still_deletes_aged_files_with_no_pending_rows(self):
        self._config(False)
        done = {**_row(pid="x-1", kind="learning_add", project="w", content="c", type_="pattern"), "status": "accepted"}
        path = self._file((self.today - timedelta(days=80)).isoformat(), [done], gz=True, age_days=80)
        self._run()
        self.assertFalse(path.exists())


if __name__ == "__main__":
    unittest.main()
