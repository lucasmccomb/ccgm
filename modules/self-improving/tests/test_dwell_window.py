#!/usr/bin/env python3
"""
Tests for the dwell-window store lifecycle (optimistic-memory §3.2, Epic 1).

Covers:
  - `dwell_until` propagation from op-event -> projected head (the P0
    regression-lock -- write-to-disk alone is inert without this).
  - `search()`'s `include_dwelling` guard: hidden by default, present via
    `load_all()` (CAS/by-id resolution must still work), present with
    `include_dwelling=True`, present by default once the window closes.
  - `is_dwelling()`: absent/malformed -> False; future -> True; past ->
    False; explicit `now` override.
  - The "only extends, never shortens" invariant, enforced at the fold
    layer for both `supersede` and `verify --dwell-hours`.
  - `ccgm-learnings-search --include-dwelling` CLI wiring.
  - The `--auto` flag widened to add/contradict/deprecate/supersede
    (adrev-opt-008), asserted against the real CLI write path.

Runs in isolation: redirects LEARNINGS_ROOT to a tempdir so tests never
touch the real ~/.claude/learnings/ store. Mirrors the isolation pattern
in test_learnings_store.py exactly (see that file's comments for why the
sys.modules.pop() and env-var-before-import ordering matter).

Run with: python3 -m pytest modules/self-improving/tests/test_dwell_window.py -q
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

# See test_learnings_store.py's identical guard (#764): drop any
# pre-existing `learnings_store` module-cache entry from an earlier import
# under the same bare name (e.g. modules/dreaming's transcript_miner.py
# also imports it) before re-importing, so this file's CCGM_LEARNINGS_DIR
# override below is guaranteed to take effect rather than reusing a stale
# cached module pointed at a different store.
sys.modules.pop("learnings_store", None)

_TMP = tempfile.mkdtemp(prefix="ccgm-dwell-test-")
_ORIG_CCGM_LEARNINGS_DIR = os.environ.get("CCGM_LEARNINGS_DIR")
os.environ["CCGM_LEARNINGS_DIR"] = _TMP

import learnings_store as ls  # noqa: E402

CLI_PATH = HERE.parent / "bin" / "ccgm-learnings-log"
SEARCH_CLI_PATH = HERE.parent / "bin" / "ccgm-learnings-search"


def tearDownModule() -> None:
    """Undo the module-level CCGM_LEARNINGS_DIR override (see
    test_learnings_store.py's identical function for the full #764
    rationale: this must run so a leaked env var cannot break a different
    test module collected later in the same pytest process)."""
    if _ORIG_CCGM_LEARNINGS_DIR is not None:
        os.environ["CCGM_LEARNINGS_DIR"] = _ORIG_CCGM_LEARNINGS_DIR
    else:
        os.environ.pop("CCGM_LEARNINGS_DIR", None)
    shutil.rmtree(_TMP, ignore_errors=True)
    shutil.rmtree(ls.LEARNINGS_CACHE_ROOT, ignore_errors=True)


def _isolate_env(testcase: unittest.TestCase, key: str) -> None:
    """Snapshot os.environ[key] and register a restoring addCleanup --
    identical helper to test_learnings_store.py's, duplicated here so this
    file has no import-time dependency on that module."""
    had_prior = key in os.environ
    prior = os.environ.get(key)

    def _restore() -> None:
        if had_prior:
            os.environ[key] = prior
        else:
            os.environ.pop(key, None)

    testcase.addCleanup(_restore)


class DwellPropagationTests(unittest.TestCase):
    """The P0 regression-lock: an op-event written with `dwell_until`
    must be readable back on the PROJECTED HEAD, not just present on the
    op-event line on disk."""

    def setUp(self):
        self.slug = f"dwell-add-{int(time.time() * 1e6)}"
        _isolate_env(self, "CCGM_LEARNINGS_PROJECT")
        os.environ["CCGM_LEARNINGS_PROJECT"] = self.slug

    def tearDown(self):
        shutil.rmtree(ls.project_dir(self.slug), ignore_errors=True)
        shutil.rmtree(ls._cache_dir(self.slug), ignore_errors=True)

    def test_add_dwell_until_propagates_to_load_all_head(self):
        dwell = ls.dwell_until_from_hours(1)
        e = ls.build_entry(type_="pattern", content="dwelling propagation target",
                            confidence=7, dwell_until=dwell)
        ls.append_entry(e)

        heads = ls.load_all(self.slug)
        self.assertEqual(len(heads), 1)
        self.assertEqual(heads[0].get("dwell_until"), dwell)

    def test_add_without_dwell_hours_is_immediately_live(self):
        # Backward compatibility: absent dwell_until means live (no key on
        # the op-event, no key on the head -- same "absence == default"
        # convention as `auto`).
        e = ls.build_entry(type_="pattern", content="no dwell target", confidence=7)
        ls.append_entry(e)
        head = ls.load_all(self.slug)[0]
        self.assertIsNone(head.get("dwell_until"))
        self.assertFalse(ls.is_dwelling(head))


class DwellSearchVisibilityTests(unittest.TestCase):
    """search()'s include_dwelling guard: hidden by default, resolvable via
    load_all() (CAS/by-id must still work), surfaced by the flag, and
    surfaced by default once the window has closed."""

    def setUp(self):
        self.slug = f"dwell-search-{int(time.time() * 1e6)}"
        _isolate_env(self, "CCGM_LEARNINGS_PROJECT")
        os.environ["CCGM_LEARNINGS_PROJECT"] = self.slug

    def tearDown(self):
        shutil.rmtree(ls.project_dir(self.slug), ignore_errors=True)
        shutil.rmtree(ls._cache_dir(self.slug), ignore_errors=True)

    def test_dwelling_row_hidden_from_default_search(self):
        dwell = ls.dwell_until_from_hours(1)
        e = ls.build_entry(type_="pattern", content="dwelling search visibility target",
                            confidence=7, dwell_until=dwell)
        ls.append_entry(e)

        results = ls.search(slug=self.slug, query="dwelling search visibility target")
        self.assertNotIn(e["id"], [r["id"] for r in results])

    def test_dwelling_row_still_resolvable_via_load_all(self):
        # load_all()/by-id resolution (update_entry_by_id, supersede_entry,
        # the CAS re-check) must still see a dwelling row -- only the
        # ranked search() result set hides it (integration-map.md §A.5/A.9).
        dwell = ls.dwell_until_from_hours(1)
        e = ls.build_entry(type_="pattern", content="dwelling load-all target",
                            confidence=7, dwell_until=dwell)
        ls.append_entry(e)

        heads = ls.load_all(self.slug)
        self.assertEqual(len(heads), 1)
        self.assertEqual(heads[0]["id"], e["id"])

    def test_dwelling_row_surfaced_by_include_dwelling(self):
        dwell = ls.dwell_until_from_hours(1)
        e = ls.build_entry(type_="pattern", content="dwelling flag surfaced target",
                            confidence=7, dwell_until=dwell)
        ls.append_entry(e)

        surfaced = ls.search(slug=self.slug, query="dwelling flag surfaced target",
                              include_dwelling=True)
        self.assertIn(e["id"], [r["id"] for r in surfaced])

    def test_row_present_in_default_search_once_window_has_closed(self):
        # Constructed with dwell_until firmly in the PAST relative to real
        # wall-clock time.time() (which search() uses internally and takes
        # no `now` override for) -- deterministic, no sleep required.
        past_dwell = ls.dwell_until_from_hours(-1)
        e = ls.build_entry(type_="pattern", content="dwell window closed target",
                            confidence=7, dwell_until=past_dwell)
        ls.append_entry(e)

        results = ls.search(slug=self.slug, query="dwell window closed target")
        self.assertIn(e["id"], [r["id"] for r in results])


class IsDwellingTests(unittest.TestCase):
    """Unit tests for the pure is_dwelling() helper."""

    def test_false_for_absent(self):
        self.assertFalse(ls.is_dwelling({}))

    def test_false_for_malformed(self):
        self.assertFalse(ls.is_dwelling({"dwell_until": "not-a-real-timestamp"}))

    def test_true_for_future(self):
        future = ls.dwell_until_from_hours(1)
        self.assertTrue(ls.is_dwelling({"dwell_until": future}))

    def test_false_for_past(self):
        past = ls.dwell_until_from_hours(-1)
        self.assertFalse(ls.is_dwelling({"dwell_until": past}))

    def test_respects_explicit_now_override(self):
        dwell = ls.dwell_until_from_hours(1)
        parsed = ls._parse_iso(dwell)
        self.assertTrue(ls.is_dwelling({"dwell_until": dwell}, now=parsed - 10))
        self.assertFalse(ls.is_dwelling({"dwell_until": dwell}, now=parsed + 10))

    def test_false_for_non_string_truthy_types_does_not_raise(self):
        # A non-string truthy `dwell_until` (a raw epoch int/float from a
        # caller that bypassed `dwell_until_from_hours()`, a corrupted
        # merge artifact, or a hand-edited shard) must fail open to "not
        # dwelling" rather than raise a TypeError out of `_parse_iso`'s
        # `datetime.strptime` call (Stage-1 review finding: an uncaught
        # TypeError here crashes `search()` for the whole project slug).
        for bad_value in (12345, 12345.6, True, [1, 2, 3]):
            with self.subTest(bad_value=bad_value):
                self.assertFalse(ls.is_dwelling({"dwell_until": bad_value}))


class MalformedDwellUntilFailOpenTests(unittest.TestCase):
    """End-to-end reproduction of the Stage-1 review finding: a non-string
    `dwell_until` on ONE row (a future caller bypassing
    `dwell_until_from_hours()`, a corrupted merge artifact, or a hand-edited
    shard) must never crash `search()` for the entire project slug -- it
    must fail open and the rest of the pool must still surface normally."""

    def setUp(self):
        self.slug = f"dwell-malformed-{int(time.time() * 1e6)}"
        _isolate_env(self, "CCGM_LEARNINGS_PROJECT")
        os.environ["CCGM_LEARNINGS_PROJECT"] = self.slug

    def tearDown(self):
        shutil.rmtree(ls.project_dir(self.slug), ignore_errors=True)
        shutil.rmtree(ls._cache_dir(self.slug), ignore_errors=True)

    def test_search_survives_a_non_string_dwell_until_row_on_disk(self):
        healthy = ls.build_entry(type_="pattern", content="healthy dwell fail-open target",
                                  confidence=7)
        ls.append_entry(healthy)

        # dwell_until=12345 is not a schema violation (validate_entry()
        # does not type-check this field) -- exactly how a raw epoch int
        # would land on disk from a caller that skipped
        # dwell_until_from_hours()'s string formatting.
        malformed = ls.build_entry(type_="pattern", content="malformed dwell fail-open target",
                                    confidence=7, dwell_until=12345)
        ls.append_entry(malformed)

        results = ls.search(slug=self.slug, query="")
        ids = [r["id"] for r in results]
        self.assertIn(healthy["id"], ids)


class DwellInvariantTests(unittest.TestCase):
    """The 'only extends, never shortens' invariant, enforced at the fold
    layer for both supersede and verify/contradict/deprecate --dwell-hours."""

    def setUp(self):
        self.slug = f"dwell-invariant-{int(time.time() * 1e6)}"
        _isolate_env(self, "CCGM_LEARNINGS_PROJECT")
        os.environ["CCGM_LEARNINGS_PROJECT"] = self.slug

    def tearDown(self):
        shutil.rmtree(ls.project_dir(self.slug), ignore_errors=True)
        shutil.rmtree(ls._cache_dir(self.slug), ignore_errors=True)

    def test_supersede_cannot_shorten_targets_dwell(self):
        long_dwell = ls.dwell_until_from_hours(10)
        e = ls.build_entry(type_="pattern", content="quarantined supersede target",
                            confidence=8, dwell_until=long_dwell)
        ls.append_entry(e)
        sha = ls.content_sha256(e["content"])

        short_dwell = ls.dwell_until_from_hours(1)
        new_entry = ls.supersede_entry(
            e["id"], content="rewritten sooner-exposed content",
            expected_sha256=sha, dwell_until=short_dwell,
        )
        heads = {h["id"]: h for h in ls.load_all(self.slug)}
        new_head = heads[new_entry["id"]]
        self.assertEqual(new_head["dwell_until"], long_dwell)

    def test_supersede_extends_when_new_dwell_is_longer(self):
        short_dwell = ls.dwell_until_from_hours(1)
        e = ls.build_entry(type_="pattern", content="extend via supersede target",
                            confidence=8, dwell_until=short_dwell)
        ls.append_entry(e)
        sha = ls.content_sha256(e["content"])

        longer_dwell = ls.dwell_until_from_hours(10)
        new_entry = ls.supersede_entry(
            e["id"], content="rewritten with a longer dwell",
            expected_sha256=sha, dwell_until=longer_dwell,
        )
        heads = {h["id"]: h for h in ls.load_all(self.slug)}
        new_head = heads[new_entry["id"]]
        self.assertEqual(new_head["dwell_until"], longer_dwell)

    def test_supersede_return_value_threads_the_requested_dwell_floor(self):
        # Stage-1 review finding: build_entry(...) inside supersede_entry()
        # omitted dwell_until=dwell_until, so the RETURNED dict always
        # reported dwell_until=None even though the op-row and the
        # projected head correctly persisted the floor. On a target with
        # no prior dwell (the common case), the returned entry's
        # dwell_until must match the requested floor.
        e = ls.build_entry(type_="pattern", content="supersede return value target",
                            confidence=8)
        ls.append_entry(e)
        sha = ls.content_sha256(e["content"])

        floor = ls.dwell_until_from_hours(5)
        new_entry = ls.supersede_entry(
            e["id"], content="revised content for return value check",
            expected_sha256=sha, dwell_until=floor,
        )
        self.assertEqual(new_entry["dwell_until"], floor)

    def test_verify_dwell_hours_cannot_shorten_targets_dwell(self):
        long_dwell = ls.dwell_until_from_hours(10)
        e = ls.build_entry(type_="pattern", content="verify shorten target",
                            confidence=8, dwell_until=long_dwell)
        ls.append_entry(e)

        short_dwell = ls.dwell_until_from_hours(1)
        self.assertTrue(ls.update_entry_by_id(e["id"], verify=True, dwell_until=short_dwell))

        head = ls.load_all(self.slug)[0]
        self.assertEqual(head["dwell_until"], long_dwell)

    def test_verify_dwell_hours_extends_when_longer(self):
        short_dwell = ls.dwell_until_from_hours(1)
        e = ls.build_entry(type_="pattern", content="verify extend target",
                            confidence=8, dwell_until=short_dwell)
        ls.append_entry(e)

        longer_dwell = ls.dwell_until_from_hours(10)
        self.assertTrue(ls.update_entry_by_id(e["id"], verify=True, dwell_until=longer_dwell))

        head = ls.load_all(self.slug)[0]
        self.assertEqual(head["dwell_until"], longer_dwell)

    def test_contradict_dwell_hours_cannot_shorten_targets_dwell(self):
        long_dwell = ls.dwell_until_from_hours(10)
        e = ls.build_entry(type_="pattern", content="contradict shorten target",
                            confidence=8, dwell_until=long_dwell)
        ls.append_entry(e)

        short_dwell = ls.dwell_until_from_hours(1)
        self.assertTrue(ls.update_entry_by_id(e["id"], contradict=True, dwell_until=short_dwell))

        head = ls.load_all(self.slug)[0]
        self.assertEqual(head["dwell_until"], long_dwell)

    def test_deprecate_dwell_hours_cannot_shorten_targets_dwell(self):
        long_dwell = ls.dwell_until_from_hours(10)
        e = ls.build_entry(type_="pattern", content="deprecate shorten target",
                            confidence=8, dwell_until=long_dwell)
        ls.append_entry(e)

        short_dwell = ls.dwell_until_from_hours(1)
        self.assertTrue(ls.update_entry_by_id(e["id"], deprecate=True, dwell_until=short_dwell))

        head = ls.load_all(self.slug)[0]
        self.assertEqual(head["dwell_until"], long_dwell)

    def test_verify_dwell_hours_starts_a_dwell_when_target_had_none(self):
        # existing=None adopts the new floor outright (max() with -infinity).
        e = ls.build_entry(type_="pattern", content="verify starts dwell target", confidence=8)
        ls.append_entry(e)
        self.assertIsNone(ls.load_all(self.slug)[0].get("dwell_until"))

        new_dwell = ls.dwell_until_from_hours(1)
        self.assertTrue(ls.update_entry_by_id(e["id"], verify=True, dwell_until=new_dwell))
        head = ls.load_all(self.slug)[0]
        self.assertEqual(head["dwell_until"], new_dwell)


class MaxDwellHelperTests(unittest.TestCase):
    """Direct unit coverage of the _max_dwell() comparison helper."""

    def test_new_none_keeps_existing(self):
        existing = ls.dwell_until_from_hours(5)
        self.assertEqual(ls._max_dwell(existing, None), existing)

    def test_existing_none_adopts_new(self):
        new = ls.dwell_until_from_hours(5)
        self.assertEqual(ls._max_dwell(None, new), new)

    def test_both_none_stays_none(self):
        self.assertIsNone(ls._max_dwell(None, None))

    def test_later_new_wins(self):
        existing = ls.dwell_until_from_hours(1)
        new = ls.dwell_until_from_hours(10)
        self.assertEqual(ls._max_dwell(existing, new), new)

    def test_earlier_new_loses(self):
        existing = ls.dwell_until_from_hours(10)
        new = ls.dwell_until_from_hours(1)
        self.assertEqual(ls._max_dwell(existing, new), existing)

    def test_malformed_existing_loses_to_valid_new(self):
        new = ls.dwell_until_from_hours(1)
        self.assertEqual(ls._max_dwell("not-a-date", new), new)

    def test_malformed_new_does_not_override_valid_existing(self):
        existing = ls.dwell_until_from_hours(1)
        self.assertEqual(ls._max_dwell(existing, "not-a-date"), existing)

    def test_non_string_existing_loses_to_valid_new_without_raising(self):
        new = ls.dwell_until_from_hours(1)
        self.assertEqual(ls._max_dwell(12345, new), new)

    def test_non_string_new_does_not_override_valid_existing_without_raising(self):
        existing = ls.dwell_until_from_hours(1)
        self.assertEqual(ls._max_dwell(existing, 12345), existing)


# ---------------------------------------------------------------------------
# CLI wiring
# ---------------------------------------------------------------------------

class DwellCLITests(unittest.TestCase):
    def setUp(self):
        self.slug = f"dwell-cli-{int(time.time() * 1e6)}"

    def _env(self, **extra) -> dict:
        # Pin the store dir to THIS module's frozen LEARNINGS_ROOT (matches
        # test_learnings_store.py's CLIExitCodeTests._env() rationale: a
        # sibling test module's import-time CCGM_LEARNINGS_DIR override,
        # collected in the same pytest run, must not leak into the
        # subprocess launched here).
        env = os.environ.copy()
        env["CCGM_LEARNINGS_DIR"] = str(ls.LEARNINGS_ROOT)
        env["CCGM_LEARNINGS_PROJECT"] = self.slug
        env.update(extra)
        return env

    def _run_log(self, args: list) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(CLI_PATH)] + args,
            env=self._env(), capture_output=True, text=True,
        )

    def _run_search(self, args: list) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(SEARCH_CLI_PATH)] + args,
            env=self._env(), capture_output=True, text=True,
        )

    def tearDown(self):
        shutil.rmtree(ls.project_dir(self.slug), ignore_errors=True)
        shutil.rmtree(ls._cache_dir(self.slug), ignore_errors=True)

    def _shard_rows(self) -> list:
        shard = ls.agent_shard_path(self.slug, ls.agent_id())
        if not shard.is_file():
            return []
        return [json.loads(ln) for ln in shard.read_text().splitlines() if ln.strip()]

    def _only_row(self, *, op: str, target_id, entry_id: str | None = None) -> dict:
        rows = [r for r in self._shard_rows() if r.get("op") == op and r.get("target_id") == target_id]
        if entry_id is not None:
            rows = [r for r in rows if r.get("id") == entry_id]
        self.assertEqual(len(rows), 1, f"expected exactly one {op} row, got {rows}")
        return rows[0]

    def test_cli_include_dwelling_flag_surfaces_dwelling_row(self):
        add = self._run_log([
            "--type", "pattern", "--content", "cli dwelling search target",
            "--dwell-hours", "1",
        ])
        self.assertEqual(add.returncode, 0, add.stderr)
        entry_id = json.loads(add.stdout)["id"]

        bare = self._run_search([
            "--project", self.slug, "--query", "cli dwelling search target", "--format", "jsonl",
        ])
        self.assertEqual(bare.returncode, 0, bare.stderr)
        self.assertNotIn(entry_id, bare.stdout)

        surfaced = self._run_search([
            "--project", self.slug, "--query", "cli dwelling search target",
            "--include-dwelling", "--format", "jsonl",
        ])
        self.assertEqual(surfaced.returncode, 0, surfaced.stderr)
        self.assertIn(entry_id, surfaced.stdout)

    def test_cli_add_auto_flag_writes_auto_true_on_disk(self):
        result = self._run_log([
            "--type", "pattern", "--content", "cli auto add target", "--auto",
        ])
        self.assertEqual(result.returncode, 0, result.stderr)
        entry_id = json.loads(result.stdout)["id"]
        row = self._only_row(op="add", target_id=None, entry_id=entry_id)
        self.assertIs(row.get("auto"), True)

    def test_cli_add_without_auto_omits_the_key(self):
        result = self._run_log(["--type", "pattern", "--content", "cli non-auto add target"])
        self.assertEqual(result.returncode, 0, result.stderr)
        entry_id = json.loads(result.stdout)["id"]
        row = self._only_row(op="add", target_id=None, entry_id=entry_id)
        self.assertNotIn("auto", row)

    def test_cli_contradict_auto_flag_writes_auto_true_on_disk(self):
        add = self._run_log(["--type", "pattern", "--content", "cli auto contradict target"])
        entry_id = json.loads(add.stdout)["id"]

        result = self._run_log(["contradict", entry_id, "--project", self.slug, "--auto"])
        self.assertEqual(result.returncode, 0, result.stderr)
        row = self._only_row(op="contradict", target_id=entry_id)
        self.assertIs(row.get("auto"), True)

    def test_cli_deprecate_auto_flag_writes_auto_true_on_disk(self):
        content = "cli auto deprecate target"
        add = self._run_log(["--type", "pattern", "--content", content])
        entry_id = json.loads(add.stdout)["id"]
        sha = ls.content_sha256(content)

        result = self._run_log([
            "deprecate", entry_id, "--project", self.slug, "--expected-sha", sha, "--auto",
        ])
        self.assertEqual(result.returncode, 0, result.stderr)
        row = self._only_row(op="deprecate", target_id=entry_id)
        self.assertIs(row.get("auto"), True)

    def test_cli_supersede_auto_flag_writes_auto_true_on_disk(self):
        content = "cli auto supersede target"
        add = self._run_log(["--type", "pattern", "--content", content])
        entry_id = json.loads(add.stdout)["id"]
        sha = ls.content_sha256(content)

        result = self._run_log([
            "supersede", entry_id, "--project", self.slug,
            "--content", "revised via cli auto supersede", "--expected-sha", sha, "--auto",
        ])
        self.assertEqual(result.returncode, 0, result.stderr)
        new_id = json.loads(result.stdout)["id"]
        row = self._only_row(op="supersede", target_id=entry_id, entry_id=new_id)
        self.assertIs(row.get("auto"), True)

    def test_cli_verify_dwell_hours_floor_reaches_the_head(self):
        long_dwell_hours = 10
        add = self._run_log([
            "--type", "pattern", "--content", "cli verify dwell floor target",
            "--dwell-hours", str(long_dwell_hours),
        ])
        self.assertEqual(add.returncode, 0, add.stderr)
        entry_id = json.loads(add.stdout)["id"]
        before = ls.load_all(self.slug)[0]

        result = self._run_log([
            "verify", entry_id, "--project", self.slug, "--dwell-hours", "1",
        ])
        self.assertEqual(result.returncode, 0, result.stderr)

        after = ls.load_all(self.slug)[0]
        # A 1-hour floor must not shorten the existing ~10-hour dwell.
        self.assertEqual(after["dwell_until"], before["dwell_until"])


def _cleanup():
    shutil.rmtree(_TMP, ignore_errors=True)
    shutil.rmtree(ls.LEARNINGS_CACHE_ROOT, ignore_errors=True)


if __name__ == "__main__":
    try:
        unittest.main(verbosity=2, exit=False)
    finally:
        _cleanup()
