#!/usr/bin/env python3
"""
Tests for the optional `trigger` field on a learning (#1098 Phase 4.1).

A dreamed learning carries the deterministic matcher its proposal was
validated with ({"kind", "value"}, see modules/dreaming/lib/triggers.py), so
the nightly recurrence metric can scan later transcripts for it. The store
only checks the shape; dreaming owns the matcher semantics.

Covers: build_entry validation, the add op-event and projected head, the
supersede path (new trigger, or the old one inherited), promote_to_global,
and the `--trigger` CLI flag on add and supersede.

Runs in isolation: CCGM_LEARNINGS_DIR points at a tempdir before import
(same pattern as test_dwell_window.py).

Run with: python3 -m pytest modules/self-improving/tests/test_trigger_field.py -q
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "lib"))

sys.modules.pop("learnings_store", None)

_TMP = tempfile.mkdtemp(prefix="ccgm-trigger-test-")
_ORIG_CCGM_LEARNINGS_DIR = os.environ.get("CCGM_LEARNINGS_DIR")
os.environ["CCGM_LEARNINGS_DIR"] = _TMP

import learnings_store as ls  # noqa: E402

CLI_PATH = HERE.parent / "bin" / "ccgm-learnings-log"

TRIGGER = {"kind": "command_prefix", "value": "git push --force"}


def tearDownModule() -> None:
    if _ORIG_CCGM_LEARNINGS_DIR is not None:
        os.environ["CCGM_LEARNINGS_DIR"] = _ORIG_CCGM_LEARNINGS_DIR
    else:
        os.environ.pop("CCGM_LEARNINGS_DIR", None)
    shutil.rmtree(_TMP, ignore_errors=True)
    shutil.rmtree(ls.LEARNINGS_CACHE_ROOT, ignore_errors=True)


def _slug(label: str) -> str:
    return f"{label}-{int(time.time() * 1e6)}"


def _head(slug: str, entry_id: str) -> dict:
    heads = ls.project_slug(slug, use_snapshot=False)["heads"]
    return next(h for h in heads if h["id"] == entry_id)


class TriggerValidationTests(unittest.TestCase):
    def test_build_entry_without_trigger_carries_none(self):
        e = ls.build_entry(type_="pattern", content="no trigger", project="x")
        self.assertIsNone(e["trigger"])

    def test_build_entry_keeps_a_valid_trigger(self):
        e = ls.build_entry(type_="pattern", content="t", project="x", trigger=TRIGGER)
        self.assertEqual(e["trigger"], TRIGGER)

    def test_phrase_set_value_list_is_accepted(self):
        trig = {"kind": "phrase_set", "value": ["wrong branch", "on main"]}
        e = ls.build_entry(type_="pattern", content="t", project="x", trigger=trig)
        self.assertEqual(e["trigger"], trig)

    def test_malformed_triggers_are_rejected(self):
        for bad in ("git push", {"kind": "regex"}, {"value": "x"}, {"kind": "", "value": "x"},
                    {"kind": "regex", "value": 3}, {"kind": "phrase_set", "value": [1, 2]}):
            with self.subTest(bad=bad), self.assertRaises(ls.ValidationError):
                ls.build_entry(type_="pattern", content="t", project="x", trigger=bad)


class TriggerPersistenceTests(unittest.TestCase):
    def setUp(self):
        self.slug = _slug("trigger")

    def tearDown(self):
        shutil.rmtree(ls.project_dir(self.slug), ignore_errors=True)
        shutil.rmtree(ls._cache_dir(self.slug), ignore_errors=True)

    def _add(self, **kw) -> str:
        e = ls.build_entry(type_="pattern", content=kw.pop("content", "base fact"), project=self.slug, **kw)
        ls.append_entry(e, slug=self.slug)
        return e["id"]

    def test_add_writes_trigger_onto_op_event_and_head(self):
        eid = self._add(trigger=TRIGGER)
        rows = ls._read_jsonl_file(ls.agent_shard_path(self.slug, ls.agent_id()))
        self.assertEqual([r.get("trigger") for r in rows if r["id"] == eid], [TRIGGER])
        self.assertEqual(_head(self.slug, eid)["trigger"], TRIGGER)

    def test_add_without_trigger_leaves_op_event_unchanged(self):
        eid = self._add()
        rows = ls._read_jsonl_file(ls.agent_shard_path(self.slug, ls.agent_id()))
        self.assertNotIn("trigger", next(r for r in rows if r["id"] == eid))
        self.assertIsNone(_head(self.slug, eid)["trigger"])

    def test_supersede_with_new_trigger_replaces_it(self):
        old = self._add(trigger=TRIGGER)
        new_trig = {"kind": "regex", "value": "force[- ]push"}
        new = ls.supersede_entry(old, content="reworded fact", slug=self.slug, trigger=new_trig)
        self.assertEqual(_head(self.slug, new["id"])["trigger"], new_trig)

    def test_supersede_without_trigger_inherits_the_old_one(self):
        old = self._add(trigger=TRIGGER)
        new = ls.supersede_entry(old, content="reworded fact", slug=self.slug)
        self.assertEqual(new["trigger"], TRIGGER)
        self.assertEqual(_head(self.slug, new["id"])["trigger"], TRIGGER)


class TriggerCLITests(unittest.TestCase):
    def setUp(self):
        self.slug = _slug("trigger-cli")

    def tearDown(self):
        shutil.rmtree(ls.project_dir(self.slug), ignore_errors=True)
        shutil.rmtree(ls._cache_dir(self.slug), ignore_errors=True)

    def _run(self, args: list) -> subprocess.CompletedProcess:
        env = os.environ.copy()
        env["CCGM_LEARNINGS_DIR"] = str(ls.LEARNINGS_ROOT)
        env["CCGM_LEARNINGS_PROJECT"] = self.slug
        return subprocess.run([sys.executable, str(CLI_PATH)] + args, env=env, capture_output=True, text=True)

    def test_add_and_supersede_accept_trigger_json(self):
        add = self._run(["--type", "pattern", "--content", "cli trigger fact", "--project", self.slug,
                         "--trigger", json.dumps(TRIGGER)])
        self.assertEqual(add.returncode, 0, add.stderr)
        eid = json.loads(add.stdout.strip().splitlines()[-1])["id"]
        self.assertEqual(_head(self.slug, eid)["trigger"], TRIGGER)

        sha = ls.content_sha256(_head(self.slug, eid)["content"])
        new_trig = {"kind": "path_glob", "value": "*.lock"}
        sup = self._run(["supersede", eid, "--content", "cli trigger fact v2", "--project", self.slug,
                         "--expected-sha", sha, "--trigger", json.dumps(new_trig)])
        self.assertEqual(sup.returncode, 0, sup.stderr)
        new_id = json.loads(sup.stdout.strip().splitlines()[-1])["id"]
        self.assertEqual(_head(self.slug, new_id)["trigger"], new_trig)

    def test_bad_trigger_json_exits_2(self):
        for bad in ("not json", json.dumps({"kind": "regex"})):
            with self.subTest(bad=bad):
                proc = self._run(["--type", "pattern", "--content", "x", "--project", self.slug, "--trigger", bad])
                self.assertEqual(proc.returncode, 2, proc.stderr)


if __name__ == "__main__":
    unittest.main()
