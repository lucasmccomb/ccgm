#!/usr/bin/env python3
"""
Tests for the recurrence metric (#1098 Phase 4.1 + 4.3): lib/recurrence.py,
the trigger copied onto the store row at integration, the recurrence summary
in health.json, and the scorecard headline.

The acceptance fixtures from the RCA:
  * learning L, injected in 6 sessions, 0 trigger hits after integration vs
    4 of 6 before -> one auto `verify`, audited;
  * injected in 6 sessions with 5 hits -> `deprecate`, with dwell;
  * 3 exposed sessions -> no action (below the 5-session floor);
  * a spike after a new batch -> a content anomaly through the breaker seam,
    which reverts that batch (against a temp git-backed learnings store);
  * the step writes no API spend;
  * the scorecard shows the dreamed and observed numbers.

Runs in isolation: CCGM_LEARNINGS_DIR, CCGM_DREAMING_DIR,
CCGM_CLAUDE_PROJECTS_DIR and HOME point at tempdirs before import (same
pattern as test_optimistic_engine.py). No network, no API key.

Run with: python3 -m pytest modules/dreaming/tests/test_recurrence.py -q
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
import uuid
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
MODULE = HERE.parent
sys.path.insert(0, str(MODULE / "lib"))

for _name in ("learnings_store", "dream_analyze", "apply_dream_proposal", "recurrence"):
    sys.modules.pop(_name, None)

_TMP_LEARNINGS = tempfile.mkdtemp(prefix="ccgm-recurrence-learnings-")
_TMP_DREAMING = tempfile.mkdtemp(prefix="ccgm-recurrence-dreaming-")
_TMP_PROJECTS = tempfile.mkdtemp(prefix="ccgm-recurrence-projects-")
_TMP_HOME = tempfile.mkdtemp(prefix="ccgm-recurrence-home-")
_TMP_WORK = tempfile.mkdtemp(prefix="ccgm-recurrence-work-")
_ORIG = {k: os.environ.get(k) for k in ("CCGM_LEARNINGS_DIR", "CCGM_DREAMING_DIR", "CCGM_CLAUDE_PROJECTS_DIR", "HOME")}
os.environ["CCGM_LEARNINGS_DIR"] = _TMP_LEARNINGS
os.environ["CCGM_DREAMING_DIR"] = _TMP_DREAMING
os.environ["CCGM_CLAUDE_PROJECTS_DIR"] = _TMP_PROJECTS
os.environ["HOME"] = _TMP_HOME

import apply_dream_proposal as adp  # noqa: E402
import dream_analyze as da  # noqa: E402
import health  # noqa: E402
import learnings_store as ls  # noqa: E402
import recurrence  # noqa: E402
import scorecard  # noqa: E402

DAY = 86400.0
RM_TRIGGER = {"kind": "command_prefix", "value": "rm -rf build"}
SYNC_BIN = str(MODULE.parent / "self-improving" / "bin" / "ccgm-learnings-sync")


def tearDownModule() -> None:
    for key, orig in _ORIG.items():
        if orig is not None:
            os.environ[key] = orig
        else:
            os.environ.pop(key, None)


def _iso(epoch: float) -> str:
    dt = datetime.fromtimestamp(epoch, tz=timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def _sid() -> str:
    return str(uuid.uuid4())


class Fixture:
    """Writes transcripts, injection-log rows and store rows for one slug."""

    def __init__(self, label: str):
        self.slug = f"{label}-{uuid.uuid4().hex[:8]}"
        self.cwd = str(Path(_TMP_WORK) / self.slug)
        Path(self.cwd).mkdir(parents=True, exist_ok=True)
        self.project_dir = Path(_TMP_PROJECTS) / ("-work-" + self.slug)
        self.project_dir.mkdir(parents=True, exist_ok=True)

    # --- transcript lines -------------------------------------------------
    def _base(self, sid: str, ts: float, type_: str, **extra) -> dict:
        return {"type": type_, "sessionId": sid, "timestamp": _iso(ts), "cwd": self.cwd, **extra}

    def bash(self, sid: str, ts: float, command: str, **extra) -> dict:
        return self._base(sid, ts, "assistant", message={"role": "assistant", "content": [
            {"type": "tool_use", "id": f"tu-{uuid.uuid4().hex[:6]}", "name": "Bash", "input": {"command": command}},
        ]}, **extra)

    def say(self, sid: str, ts: float, text: str) -> dict:
        return self._base(sid, ts, "assistant", message={"role": "assistant", "content": [{"type": "text", "text": text}]})

    def human(self, sid: str, ts: float, text: str, **extra) -> dict:
        return self._base(sid, ts, "user", promptSource="typed", message={"role": "user", "content": text}, **extra)

    def tool_result(self, sid: str, ts: float, text: str, *, error: bool) -> dict:
        return self._base(sid, ts, "user", message={"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "tu-x", "is_error": error, "content": text},
        ]})

    def session(self, start: float, *, hit: bool, sid: str | None = None) -> str:
        """One session: a human turn, then a Bash call that hits the trigger
        when `hit`, else a harmless one."""
        sid = sid or _sid()
        command = "rm -rf build && make" if hit else "ls -la"
        self.write(sid, [self.human(sid, start, "please build it"), self.bash(sid, start + 60, command)])
        return sid

    def write(self, sid: str, lines: list[dict], *, subagent: str | None = None) -> Path:
        if subagent:
            path = self.project_dir / sid / "subagents" / f"agent-{subagent}.jsonl"
        else:
            path = self.project_dir / f"{sid}.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            for line in lines:
                fh.write(json.dumps(line) + "\n")
        return path

    # --- injection log ----------------------------------------------------
    def inject(self, sid: str, ts: float, ids: list[str]) -> None:
        day = datetime.fromtimestamp(ts, tz=timezone.utc).date().isoformat()
        path = Path(os.environ["CCGM_DREAMING_DIR"]) / "injection-log" / f"{day}.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps({
                "timestamp": _iso(ts), "session_id": sid, "source": "startup", "project_slug": self.slug,
                "injected_count": len(ids), "injected_ids": ids, "approx_tokens": 10,
            }) + "\n")

    # --- store ------------------------------------------------------------
    def learning(self, *, content: str = "never rm -rf build; run make clean", trigger=RM_TRIGGER,
                 source: str = "inferred") -> tuple[str, float]:
        e = ls.build_entry(type_="pitfall", content=content, source=source, confidence=8,
                           project=self.slug, trigger=trigger)
        ls.append_entry(e, slug=self.slug)
        return e["id"], ls._parse_iso(e["timestamp"])

    def head(self, entry_id: str) -> dict:
        return next(h for h in ls.project_slug(self.slug, use_snapshot=False)["heads"] if h["id"] == entry_id)


class RecurrenceTestBase(unittest.TestCase):
    def setUp(self) -> None:
        for key, value in (("CCGM_LEARNINGS_DIR", str(ls.LEARNINGS_ROOT)), ("CCGM_DREAMING_DIR", _TMP_DREAMING),
                           ("CCGM_CLAUDE_PROJECTS_DIR", str(ls.CLAUDE_PROJECTS_ROOT)), ("HOME", _TMP_HOME)):
            self._pin_env(key, value)
        # Every test starts from empty recurrence state, an empty audit, an
        # empty injection log and transcripts, and a clean breaker.
        for path in (recurrence.state_path(), adp.apply_audit_path()):
            path.unlink(missing_ok=True)
        for directory in (Path(_TMP_DREAMING) / "injection-log", Path(_TMP_PROJECTS)):
            if directory.is_dir():
                subprocess.run(["rm", "-rf", str(directory)], check=True)
        Path(_TMP_PROJECTS).mkdir(parents=True, exist_ok=True)
        adp._write_optimistic_state_atomic(adp._default_optimistic_state())
        self._config({})

    def _pin_env(self, key: str, value: str) -> None:
        had, prior = key in os.environ, os.environ.get(key)
        os.environ[key] = value
        self.addCleanup(lambda: os.environ.__setitem__(key, prior) if had else os.environ.pop(key, None))

    def _config(self, overrides: dict, *, enabled=True) -> None:
        cfg = {"optimistic_integration": {"enabled": enabled, **overrides}}
        (Path(_TMP_DREAMING) / "config.json").write_text(json.dumps(cfg), encoding="utf-8")

    def _audit(self) -> list[dict]:
        return adp._read_jsonl(adp.apply_audit_path())

    def _actions(self) -> list[dict]:
        return [a for a in self._audit() if a.get("posture") == "recurrence"]

    def _run(self, now: float) -> dict:
        return recurrence.run(now=now, projects_root=_TMP_PROJECTS)

    def _measured_fixture(self, label: str, *, before_hits: int, after_hits: int, exposed: int = 6,
                          before: int = 6) -> tuple[Fixture, str, float]:
        """L integrated at T. `before` sessions in the 30 days before T with
        `before_hits` hits; `exposed` sessions after T, each injected with L,
        `after_hits` of them hitting."""
        fx = Fixture(label)
        lid, t = fx.learning()
        for i in range(before):
            fx.session(t - (10 - i) * DAY, hit=i < before_hits)
        for i in range(exposed):
            start = t + DAY + i * 3600
            sid = fx.session(start, hit=i < after_hits)
            fx.inject(sid, start, [lid])
        return fx, lid, t


class ScanTextTests(unittest.TestCase):
    """What the metric reads in a transcript line, and what it ignores."""

    def setUp(self):
        self.fx = Fixture("scan")
        self.sid = _sid()

    def test_tool_inputs_errors_and_human_turns_are_scanned(self):
        t = time.time()
        self.assertEqual(recurrence.scan_texts(self.fx.bash(self.sid, t, "rm -rf build")), ["rm -rf build"])
        self.assertEqual(recurrence.scan_texts(self.fx.tool_result(self.sid, t, "fatal: bad ref", error=True)),
                         ["fatal: bad ref"])
        self.assertEqual(recurrence.scan_texts(self.fx.human(self.sid, t, "no, use the other branch")),
                         ["no, use the other branch"])

    def test_file_paths_in_tool_input_are_scanned(self):
        line = self.fx._base(self.sid, time.time(), "assistant", message={"role": "assistant", "content": [
            {"type": "tool_use", "id": "t", "name": "Edit",
             "input": {"file_path": "/r/package-lock.json", "old_string": "rm -rf build", "new_string": "x"}},
        ]})
        self.assertEqual(recurrence.scan_texts(line), ["/r/package-lock.json"])

    def test_prose_successful_results_reminders_and_subagent_prompts_are_not_scanned(self):
        t = time.time()
        self.assertEqual(recurrence.scan_texts(self.fx.say(self.sid, t, "I will not rm -rf build")), [])
        self.assertEqual(recurrence.scan_texts(self.fx.tool_result(self.sid, t, "rm -rf build", error=False)), [])
        self.assertEqual(recurrence.scan_texts(self.fx.human(
            self.sid, t, "go<system-reminder>learning: never rm -rf build</system-reminder>")), ["go"])
        self.assertEqual(recurrence.scan_texts(self.fx.human(self.sid, t, "rm -rf build", isSidechain=True)), [])


class OutcomeTests(RecurrenceTestBase):
    def test_zero_hits_after_vs_four_of_six_before_auto_verifies_once(self):
        fx, lid, t = self._measured_fixture("avoided", before_hits=4, after_hits=0)

        report = self._run(t + 3 * DAY)

        actions = self._actions()
        self.assertEqual([(a["kind"], a["target_id"], a["outcome"]) for a in actions],
                         [("learning_verify", lid, "applied")], actions)
        self.assertEqual(actions[0]["method"], "auto_apply")
        stats = actions[0]["recurrence"]
        self.assertEqual((stats["exposed_sessions"], stats["exposed_hits"]), (6, 0))
        self.assertEqual((stats["baseline_sessions"], stats["baseline_hits"]), (6, 4))
        self.assertEqual(fx.head(lid)["uses"], 1)
        self.assertEqual(report["decisions"][0]["outcome"], "avoided")

        # The next night with no new sessions does not verify again.
        self._run(t + 4 * DAY)
        self.assertEqual(len(self._actions()), 1)

    def test_five_of_six_exposed_hits_deprecates_with_dwell(self):
        fx, lid, t = self._measured_fixture("ineffective", before_hits=4, after_hits=5)

        self._run(t + 3 * DAY)

        actions = self._actions()
        self.assertEqual([(a["kind"], a["target_id"], a["outcome"]) for a in actions],
                         [("learning_deprecate", lid, "applied")], actions)
        head = fx.head(lid)
        self.assertTrue(head["deprecated"])
        self.assertIsNotNone(head["dwell_until"])
        self.assertGreater(ls._parse_iso(head["dwell_until"]), time.time() + 20 * 3600)
        self.assertEqual(recurrence.read_state()["learnings"][lid]["status"], "deprecated")

    def test_firing_with_no_baseline_needs_half_the_exposed_sessions(self):
        fx, lid, t = self._measured_fixture("no-baseline", before_hits=0, after_hits=3, before=0)
        self._run(t + 3 * DAY)
        self.assertEqual([a["kind"] for a in self._actions()], ["learning_deprecate"])

    def test_three_exposed_sessions_take_no_action(self):
        _, lid, t = self._measured_fixture("floor", before_hits=4, after_hits=0, exposed=3)

        report = self._run(t + 3 * DAY)

        self.assertEqual(self._actions(), [])
        self.assertEqual(report["decisions"], [])
        stats = recurrence.read_state()["learnings"][lid]["stats"]
        self.assertEqual(stats["exposed_sessions"], 3)

    def test_a_partial_reduction_takes_no_action(self):
        _, _, t = self._measured_fixture("partial", before_hits=4, after_hits=3)
        self._run(t + 3 * DAY)
        self.assertEqual(self._actions(), [])

    def test_shadow_mode_records_the_decision_without_writing(self):
        self._config({}, enabled="shadow")
        fx, lid, t = self._measured_fixture("shadow", before_hits=4, after_hits=0)

        report = self._run(t + 3 * DAY)

        self.assertEqual(self._actions(), [])
        self.assertEqual(fx.head(lid)["uses"], 0)
        self.assertEqual([(d["outcome"], d["action"]) for d in report["decisions"]], [("avoided", "held:shadow")])

    def test_suspended_breaker_holds_store_writes(self):
        fx, lid, t = self._measured_fixture("suspended", before_hits=4, after_hits=5)
        adp._write_optimistic_state_atomic({**adp._default_optimistic_state(), "suspended": True,
                                            "suspended_at": _iso(time.time())})
        report = self._run(t + 3 * DAY)
        self.assertEqual(self._actions(), [])
        self.assertFalse(fx.head(lid)["deprecated"])
        self.assertEqual(report["decisions"][0]["action"], "held:breaker_suspended")

    def test_deprecate_respects_the_eviction_cap(self):
        self._config({"max_eviction_absolute": 0})
        fx, lid, t = self._measured_fixture("cap", before_hits=4, after_hits=5)
        report = self._run(t + 3 * DAY)
        self.assertEqual(self._actions(), [])
        self.assertFalse(fx.head(lid)["deprecated"])
        self.assertEqual(report["decisions"][0]["action"], "held:over_cap")

    def test_global_learning_is_measured_across_slugs_but_never_written(self):
        """_global rows are measured in every slug's sessions. The store
        refuses unattended verify/deprecate on _global (admin gate), so the
        decision is held instead of failing and auditing every night."""
        fx = Fixture("global")
        # A trigger of its own: this _global row stays in the store this file
        # shares, and _global is in scope for every other test's slug.
        command = f"drop-cache-{uuid.uuid4().hex[:8]}"
        e = ls.build_entry(type_="pitfall", content=f"global fact {fx.slug}", source="inferred", confidence=8,
                           project=ls.GLOBAL_SLUG, trigger={"kind": "command_prefix", "value": command})
        self._pin_env("CCGM_LEARNINGS_ADMIN", "1")
        ls.append_entry(e, slug=ls.GLOBAL_SLUG)
        os.environ.pop("CCGM_LEARNINGS_ADMIN")
        lid, t = e["id"], ls._parse_iso(e["timestamp"])

        def session(start: float, hit: bool) -> str:
            sid = _sid()
            fx.write(sid, [fx.human(sid, start, "go"), fx.bash(sid, start + 60, command if hit else "ls")])
            return sid

        for i in range(6):
            session(t - (10 - i) * DAY, i < 4)
        for i in range(6):
            start = t + DAY + i * 3600
            fx.inject(session(start, False), start, [lid])

        report = self._run(t + 3 * DAY)

        decision = next(d for d in report["decisions"] if d["learning_id"] == lid)
        self.assertEqual((decision["outcome"], decision["action"]), ("avoided", "held:global_scope"))
        self.assertEqual(self._actions(), [])

    def test_never_triggered_in_45_days_is_left_to_decay(self):
        fx, lid, t = self._measured_fixture("dormant", before_hits=0, after_hits=0, exposed=2, before=2)
        self._run(t + 46 * DAY)
        self.assertEqual(self._actions(), [])
        self.assertEqual(recurrence.read_state()["learnings"][lid]["status"], "dormant")

    def test_learnings_without_a_trigger_are_counted_unmeasured(self):
        fx = Fixture("unmeasured")
        fx.learning(trigger=None, source="observed", content="observed in session")
        fx.learning(trigger=None, source="inferred", content="dreamed before triggers")
        self._run(time.time())
        unmeasured = recurrence.read_state()["unmeasured"]
        self.assertGreaterEqual(unmeasured["observed"], 1)
        self.assertGreaterEqual(unmeasured["dreamed"], 1)


class ScanStateTests(RecurrenceTestBase):
    def test_subagent_hits_count_toward_the_parent_session(self):
        fx = Fixture("subagent")
        lid, t = fx.learning()
        sid = fx.session(t + DAY, hit=False)
        fx.inject(sid, t + DAY, [lid])
        fx.write(sid, [fx.bash(sid, t + DAY + 120, "rm -rf build", isSidechain=True)], subagent="abc123")

        self._run(t + 2 * DAY)

        session = recurrence.read_state()["sessions"][sid]
        self.assertEqual(session["hits"], [lid])
        self.assertEqual(session["exposed"], [lid])

    def test_only_appended_bytes_are_scanned_on_the_next_night(self):
        fx = Fixture("incremental")
        lid, t = fx.learning()
        sid = fx.session(t + DAY, hit=False)
        fx.inject(sid, t + DAY, [lid])

        first = self._run(t + 2 * DAY)
        self.assertGreaterEqual(first["files_scanned"], 1)
        self.assertEqual(self._run(t + 2 * DAY + 60)["files_scanned"], 0)

        fx.write(sid, [fx.bash(sid, t + DAY + 7200, "rm -rf build")])
        third = self._run(t + 3 * DAY)
        self.assertEqual(third["files_scanned"], 1)
        self.assertEqual(recurrence.read_state()["sessions"][sid]["hits"], [lid])

    def test_the_step_writes_no_api_spend(self):
        cost_log = Path(_TMP_DREAMING) / "cost.log"
        cost_log.write_text("2026-10-01\t0.5\tanalyze\n", encoding="utf-8")
        before = cost_log.read_text(encoding="utf-8")
        _, _, t = self._measured_fixture("nospend", before_hits=4, after_hits=0)

        real_run = subprocess.run

        def guarded_run(argv, *a, **kw):
            names = [Path(str(x)).name for x in (argv if isinstance(argv, (list, tuple)) else [argv])]
            self.assertNotIn("claude", names, "the recurrence step must never call the model")
            return real_run(argv, *a, **kw)

        with unittest.mock.patch("subprocess.run", side_effect=guarded_run):
            self._run(t + 3 * DAY)

        self.assertEqual(cost_log.read_text(encoding="utf-8"), before)
        self.assertEqual(len(self._actions()), 1, "the fixture did act, so the step really ran")

    def test_nothing_to_measure_scans_nothing(self):
        """An empty store (the CI chain smoke's case) scans no transcript.
        Run through the CLI with its own empty store, since this file's
        store is shared by every test."""
        Fixture("empty").session(time.time(), hit=True)
        with tempfile.TemporaryDirectory() as tmp:
            env = {**os.environ, "CCGM_LEARNINGS_DIR": str(Path(tmp) / "learnings"),
                   "CCGM_DREAMING_DIR": str(Path(tmp) / "dreaming")}
            proc = subprocess.run([sys.executable, str(MODULE / "lib" / "recurrence.py"), "run",
                                   "--projects-root", _TMP_PROJECTS], capture_output=True, text=True, env=env)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            out = json.loads(proc.stdout.strip().splitlines()[-1])
            self.assertEqual((out["files_scanned"], out["learnings_measured"]), (0, 0), out)
            self.assertTrue((Path(tmp) / "dreaming" / "state" / "recurrence.json").is_file())


class TriggerOnIntegrationTests(RecurrenceTestBase):
    """Integration copies the proposal's trigger onto the store row."""

    def _proposal(self, pid: str, kind: str, slug: str, **kw) -> dict:
        row = {
            "id": pid, "kind": kind, "project": slug, "target_id": kw.get("target_id"),
            "content": kw.get("content", f"fact {pid}"), "type": "pitfall", "confidence": 9,
            "prevalence": {"sessions": 5, "agents": 1}, "evidence": [{"session_id": f"sess-{pid}", "excerpt": "x"}],
            "justification": "t", "fingerprint": f"fp-{pid}", "generated_at": _iso(time.time()),
            "status": "pending", "trigger": kw.get("trigger", RM_TRIGGER),
        }
        return row

    def _write_day(self, day: str, rows: list[dict]) -> None:
        path = adp.proposals_dir() / f"{day}.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")

    def test_add_and_supersede_carry_the_trigger(self):
        fx = Fixture("integrate")
        old_id, _ = fx.learning(trigger=None, content="old wording")
        new_trigger = {"kind": "regex", "value": "make: \\*\\*\\* No rule"}
        day = f"2026-test-{uuid.uuid4().hex[:8]}"
        self._write_day(day, [
            self._proposal("ti-add", "learning_add", fx.slug),
            self._proposal("ti-sup", "learning_supersede", fx.slug, target_id=old_id,
                           content="new wording", trigger=new_trigger),
        ])

        summary = adp.run_optimistic_integrate(day)

        self.assertEqual(summary["applied"], 2, summary)
        by_kind = {a["kind"]: a for a in self._audit() if a.get("outcome") == "applied"}
        self.assertEqual(fx.head(by_kind["learning_add"]["new_entry_id"])["trigger"], RM_TRIGGER)
        self.assertEqual(fx.head(by_kind["learning_supersede"]["new_entry_id"])["trigger"], new_trigger)

    def test_human_accept_carries_the_trigger(self):
        fx = Fixture("accept")
        day = f"2026-test-{uuid.uuid4().hex[:8]}"
        self._write_day(day, [self._proposal("ha-add", "learning_add", fx.slug)])
        result = adp.apply_proposal("ha-add")
        self.assertEqual(result["outcome"], "applied", result)
        self.assertEqual(fx.head(result["new_entry_id"])["trigger"], RM_TRIGGER)


class SpikeTests(RecurrenceTestBase):
    """A recurrence spike in sessions exposed to a new batch reports a
    content anomaly through the breaker seam, which reverts the batch."""

    def setUp(self) -> None:
        super().setUp()
        subprocess.run([sys.executable, SYNC_BIN, "init"], check=True, capture_output=True, text=True)
        subprocess.run([sys.executable, SYNC_BIN, "commit", "-m", "setup"], check=True, capture_output=True, text=True)

    def _integrate_batch(self, fx: Fixture) -> tuple[str, str]:
        day = f"2026-test-{uuid.uuid4().hex[:8]}"
        row = TriggerOnIntegrationTests._proposal(self, "sp-add-" + uuid.uuid4().hex[:6], "learning_add", fx.slug)
        TriggerOnIntegrationTests._write_day(self, day, [row])
        summary = adp.run_optimistic_integrate(day)
        self.assertEqual(summary["applied"], 1, summary)
        new_id = next(a["new_entry_id"] for a in self._audit()
                      if a.get("outcome") == "applied" and a.get("batch_id") == summary["batch_id"])
        return summary["batch_id"], new_id

    def test_spike_after_a_new_batch_reverts_it(self):
        fx = Fixture("spike")
        t0 = time.time()
        for i in range(3):
            fx.session(t0 - (5 - i) * DAY, hit=False)
        batch_id, lid = self._integrate_batch(fx)
        for i in range(3):
            start = t0 + DAY + i * 3600
            sid = fx.session(start, hit=True)
            fx.inject(sid, start, [lid])

        report = self._run(t0 + 2 * DAY)

        self.assertEqual([s["batch_id"] for s in report["spikes"]], [batch_id], report)
        anomaly = next(a for a in self._audit() if a.get("outcome") == "anomaly_recorded")
        self.assertEqual((anomaly["reason"], anomaly["class"]), ("recurrence_spike", "content"))
        self.assertTrue(any(a.get("outcome") == "batch_auto_reverted" and a.get("batch_id") == batch_id
                            for a in self._audit()), self._audit())
        self.assertNotIn(lid, {h["id"] for h in ls.project_slug(fx.slug, use_snapshot=False)["heads"]})

        # Reported once: the next night does not record it again.
        self._run(t0 + 2 * DAY + 60)
        self.assertEqual(sum(1 for a in self._audit() if a.get("outcome") == "anomaly_recorded"), 1)

    def test_no_spike_when_the_batch_is_quiet(self):
        fx = Fixture("quiet")
        t0 = time.time()
        for i in range(3):
            fx.session(t0 - (5 - i) * DAY, hit=False)
        _, lid = self._integrate_batch(fx)
        for i in range(3):
            start = t0 + DAY + i * 3600
            fx.inject(fx.session(start, hit=False), start, [lid])
        report = self._run(t0 + 2 * DAY)
        self.assertEqual(report["spikes"], [])
        self.assertFalse(any(a.get("outcome") == "anomaly_recorded" for a in self._audit()))


class ReportingTests(RecurrenceTestBase):
    def _seed(self) -> float:
        _, _, t = self._measured_fixture("report", before_hits=4, after_hits=1)
        self._run(t + 3 * DAY)
        return t

    def test_summary_splits_dreamed_and_observed_with_exposure(self):
        self._seed()
        s = recurrence.summary(recurrence.read_state())
        dreamed = s["dreamed"]
        self.assertEqual(dreamed["measured"], 1)
        self.assertEqual(dreamed["exposed_sessions"], 6)
        self.assertEqual(dreamed["observed_hits"], 1)
        self.assertAlmostEqual(dreamed["expected_hits"], 4.0)
        self.assertAlmostEqual(dreamed["reduction"], 0.75)
        self.assertEqual(s["observed"]["measured"], 0)
        self.assertIsNone(s["observed"]["reduction"])

    def test_health_carries_a_recurrence_summary_and_keeps_its_shape(self):
        t = self._seed()
        data = health.compute(Path(_TMP_DREAMING), datetime.fromtimestamp(t + 3 * DAY, tz=timezone.utc),
                              gate_fn=lambda **_: {"state": "open", "code": "ok", "reason": ""})
        for key in ("status", "generated_at", "last_success_at", "reasons"):
            self.assertIn(key, data)
        self.assertEqual(data["recurrence"]["dreamed"]["exposed_sessions"], 6)
        self.assertAlmostEqual(data["recurrence"]["dreamed"]["reduction"], 0.75)

    def test_scorecard_headline_shows_both_numbers_and_exposure(self):
        t = self._seed()
        md = scorecard.render(
            datetime.fromtimestamp(t - 4 * DAY, tz=timezone.utc), datetime.fromtimestamp(t + 3 * DAY, tz=timezone.utc),
            learnings_dir=ls.LEARNINGS_ROOT, injection_log_dir=Path(_TMP_DREAMING) / "injection-log",
            proposals_dir=adp.proposals_dir(), apply_audit_path=adp.apply_audit_path(), store_api=ls,
            generated_at="2026-10-04T00:00:00Z",
        )
        headline = next(line for line in md.splitlines() if line.startswith("**Recurrence reduction"))
        self.assertIn("dreamed 75% (1 learning, 6 exposed sessions)", headline)
        self.assertIn("observed n/a (0 learnings, 0 exposed sessions)", headline)
        self.assertIn("## Recurrence", md)
        self.assertIn("unmeasured (no trigger)", md)

    def test_scorecard_without_recurrence_state_says_so(self):
        md = scorecard.render(
            "2026-09-27", "2026-10-04", learnings_dir=ls.LEARNINGS_ROOT,
            injection_log_dir=Path(_TMP_DREAMING) / "injection-log", proposals_dir=adp.proposals_dir(),
            apply_audit_path=adp.apply_audit_path(), store_api=ls, generated_at="2026-10-04T00:00:00Z",
        )
        self.assertIn("**Recurrence reduction: dreamed n/a (0 learnings, 0 exposed sessions)", md)


class DailyChainTests(unittest.TestCase):
    """dream-daily.sh runs the recurrence step every night."""

    def test_chain_runs_the_recurrence_step(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "dreaming"
            bins = Path(tmp) / "bin"
            bins.mkdir()
            (bins / "dream-analyze.sh").write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
            root.mkdir()
            env = {**os.environ, "CCGM_DREAMING_DIR": str(root), "CCGM_DREAMING_BIN_DIR": str(bins),
                   "CCGM_DREAMING_LOGS_DIR": str(Path(tmp) / "logs"), "CCGM_DREAMING_TODAY": "2026-10-06",
                   "CCGM_LEARNINGS_DIR": str(Path(tmp) / "learnings"),
                   "CCGM_CLAUDE_PROJECTS_DIR": str(Path(tmp) / "projects")}
            proc = subprocess.run(["bash", str(MODULE / "bin" / "dream-daily.sh")], capture_output=True,
                                  text=True, env=env, timeout=120)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            log = (Path(tmp) / "logs" / "dreaming-daily-2026-10-06.log").read_text(encoding="utf-8")
            self.assertIn("recurrence: exit=0", log)
            self.assertTrue((root / "state" / "recurrence.json").is_file())


import unittest.mock  # noqa: E402  (used by test_the_step_writes_no_api_spend)

if __name__ == "__main__":
    unittest.main()
