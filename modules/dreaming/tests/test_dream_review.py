#!/usr/bin/env python3
"""
Tests for /dream-review's underlying primitives (optimistic-memory plan.md
Epic 6): the dwelling-set read idiom the command documents
({e for e in load_all(slug) if is_dwelling(e)}, never search()), the
per-op-kind veto reverse-op recipe (add/supersede -> deprecate;
contradict/deprecate -> verify) driven against the real ccgm-learnings-log
CLI, and ccgm-learnings-sync's new `revert <sha>` subcommand.

/dream-review itself (commands/dream-review.md) is a thin Claude-reader
command with no dedicated library module -- exactly like /dream and
/dream-apply, which have none beyond the CLIs they already shell out to.
Epic 6 adds no new lib/*.py file. This test file is therefore the
regression lock for the exact recipe the command's markdown documents: it
drives the same public, already-tested primitives
(learnings_store.load_all/is_dwelling/content_sha256, the
ccgm-learnings-log CLI, the new ccgm-learnings-sync revert verb) the agent
is instructed to combine, and pins their combined behavior. `_resolve_veto_op()`
below is a test-local mirror of the command's documented dispatch table --
not new production code (Epic 6 ships no such library function; see the
command's own docstring for why).

Runs in isolation: CCGM_LEARNINGS_DIR is redirected to a tempdir before
import (mirrors modules/self-improving/tests/test_dwell_window.py's
isolation pattern exactly -- see that file's comments for why the
sys.modules.pop() and env-var-before-import ordering matter). The
SyncRevertTests class additionally spins up its OWN scratch git store per
test (a real git repo, separate from the module-level tempdir the other
classes share) since it exercises real git history via subprocess, not
just the JSONL store. Never the real ~/.claude/learnings or
~/.claude/dreaming (#793).

Run with: python3 -m pytest modules/dreaming/tests/test_dream_review.py -q
      or: python3 modules/dreaming/tests/test_dream_review.py
"""

from __future__ import annotations

import fcntl
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
import uuid
from pathlib import Path

HERE = Path(__file__).resolve().parent
SELF_IMPROVING_LIB = HERE.parent.parent / "self-improving" / "lib"
SELF_IMPROVING_BIN = HERE.parent.parent / "self-improving" / "bin"
sys.path.insert(0, str(SELF_IMPROVING_LIB))

# See test_dwell_window.py's identical guard (#764): drop any pre-existing
# learnings_store module-cache entry from an earlier import under the same
# bare name (e.g. modules/dreaming's own transcript_miner.py also imports
# it) before re-importing, so this file's CCGM_LEARNINGS_DIR override below
# is guaranteed to take effect rather than reusing a stale cached module
# pointed at a different store.
sys.modules.pop("learnings_store", None)

_TMP = tempfile.mkdtemp(prefix="ccgm-dream-review-test-")
_ORIG_CCGM_LEARNINGS_DIR = os.environ.get("CCGM_LEARNINGS_DIR")
os.environ["CCGM_LEARNINGS_DIR"] = _TMP

import learnings_store as ls  # noqa: E402

LOG_CLI = SELF_IMPROVING_BIN / "ccgm-learnings-log"
SYNC_CLI = SELF_IMPROVING_BIN / "ccgm-learnings-sync"


def tearDownModule() -> None:
    """Undo the module-level CCGM_LEARNINGS_DIR override (see
    test_dwell_window.py's identical function for the full #764 rationale:
    this must run so a leaked env var cannot break a different test module
    collected later in the same pytest process)."""
    if _ORIG_CCGM_LEARNINGS_DIR is not None:
        os.environ["CCGM_LEARNINGS_DIR"] = _ORIG_CCGM_LEARNINGS_DIR
    else:
        os.environ.pop("CCGM_LEARNINGS_DIR", None)
    shutil.rmtree(_TMP, ignore_errors=True)
    shutil.rmtree(ls.LEARNINGS_CACHE_ROOT, ignore_errors=True)


def _isolate_env(testcase: unittest.TestCase, key: str) -> None:
    """Snapshot os.environ[key] and register a restoring addCleanup --
    identical helper to test_dwell_window.py's own, duplicated here so this
    file has no import-time dependency on that module."""
    had_prior = key in os.environ
    prior = os.environ.get(key)

    def _restore() -> None:
        if had_prior:
            os.environ[key] = prior
        else:
            os.environ.pop(key, None)

    testcase.addCleanup(_restore)


def _unique_slug(label: str) -> str:
    return f"{label}-{uuid.uuid4().hex[:8]}"


# ---------------------------------------------------------------------------
# Dwelling-set computation: {e for e in load_all(slug) if is_dwelling(e)},
# directly from load_all() -- never search(include_dwelling=True), which
# token/max-results-caps its output (plan.md Epic 6's own architecture
# finding).
# ---------------------------------------------------------------------------

class DwellingSetComputationTests(unittest.TestCase):
    def setUp(self):
        self.slug = _unique_slug("dream-review-dwell")
        _isolate_env(self, "CCGM_LEARNINGS_PROJECT")
        os.environ["CCGM_LEARNINGS_PROJECT"] = self.slug

    def tearDown(self):
        shutil.rmtree(ls.project_dir(self.slug), ignore_errors=True)
        shutil.rmtree(ls._cache_dir(self.slug), ignore_errors=True)  # noqa: SLF001

    def _dwelling_ids(self) -> set[str]:
        # The exact recipe commands/dream-review.md documents.
        return {e["id"] for e in ls.load_all(self.slug) if ls.is_dwelling(e)}

    def test_dwelling_set_returns_exactly_rows_with_future_dwell_until(self):
        future = ls.dwell_until_from_hours(1)
        past = ls.dwell_until_from_hours(-1)

        dwelling = ls.build_entry(type_="pattern", content="dwelling row", confidence=7, dwell_until=future)
        ls.append_entry(dwelling)
        closed = ls.build_entry(type_="pattern", content="dwell window closed row", confidence=7, dwell_until=past)
        ls.append_entry(closed)
        live = ls.build_entry(type_="pattern", content="never dwelt row", confidence=7)
        ls.append_entry(live)

        self.assertEqual(self._dwelling_ids(), {dwelling["id"]})

    def test_dwelling_set_empty_when_nothing_is_dwelling(self):
        e = ls.build_entry(type_="pattern", content="plain live row", confidence=7)
        ls.append_entry(e)
        self.assertEqual(self._dwelling_ids(), set())

    def test_dwelling_set_via_load_all_is_not_truncated_by_searchs_cap(self):
        # search(include_dwelling=True) token/max-results-caps its output;
        # load_all() never does. Seed more dwelling rows than the default
        # max_results cap and confirm load_all()+is_dwelling() surfaces
        # every one of them while search(include_dwelling=True) drops some
        # -- the exact architecture reasoning behind dream-review.md's
        # "never search() for this listing" instruction.
        cfg = ls.load_config()
        max_results = int(cfg.get("max_results", ls.DEFAULT_MAX_RESULTS))
        n = max_results + 5
        future = ls.dwell_until_from_hours(1)
        ids = []
        for i in range(n):
            e = ls.build_entry(
                type_="pattern",
                content=f"bulk dwelling row {i} unique-marker-xyz",
                confidence=7,
                dwell_until=future,
            )
            ls.append_entry(e)
            ids.append(e["id"])

        dwelling_ids = self._dwelling_ids()
        self.assertEqual(dwelling_ids, set(ids))
        self.assertEqual(len(dwelling_ids), n)

        capped = ls.search(
            slug=self.slug, query="unique-marker-xyz", include_dwelling=True, config=cfg,
        )
        self.assertLess(len(capped), n, "search()'s cap should drop some dwelling rows that load_all() keeps")


# ---------------------------------------------------------------------------
# Veto reverse-op recipe: add/supersede -> deprecate; contradict/deprecate
# -> verify. _resolve_veto_op() is a test-local mirror of
# commands/dream-review.md's dispatch table (Epic 6 ships no dedicated
# library function for this -- see that file's own docstring).
# ---------------------------------------------------------------------------

def _resolve_veto_op(kind: str) -> str | None:
    """Mirrors commands/dream-review.md's documented veto dispatch table.
    Keyed off the SAME posture classification
    dream_analyze.OPTIMISTIC_POSTURE assigns each kind:
    optimistic-dwell (add/supersede) reverses via deprecate;
    dwell-quarantine (contradict/deprecate) reverses via verify.
    learning_verify (optimistic-immediate) has no defined reverse op.
    Test-local mirror only -- pins the recipe the command documents; not
    itself production code."""
    if kind in ("learning_add", "learning_supersede"):
        return "deprecate"
    if kind in ("learning_contradict", "learning_deprecate"):
        return "verify"
    return None


class VetoReverseOpTests(unittest.TestCase):
    def setUp(self):
        self.slug = _unique_slug("dream-review-veto")
        self.env = os.environ.copy()
        self.env["CCGM_LEARNINGS_DIR"] = str(ls.LEARNINGS_ROOT)
        self.env["CCGM_LEARNINGS_PROJECT"] = self.slug

    def tearDown(self):
        shutil.rmtree(ls.project_dir(self.slug), ignore_errors=True)
        shutil.rmtree(ls._cache_dir(self.slug), ignore_errors=True)  # noqa: SLF001

    def _log(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(LOG_CLI), *args],
            env=self.env, capture_output=True, text=True,
        )

    def _heads(self) -> dict[str, dict]:
        return {h["id"]: h for h in ls.load_all(self.slug)}

    def test_resolve_veto_op_dispatch_table(self):
        self.assertEqual(_resolve_veto_op("learning_add"), "deprecate")
        self.assertEqual(_resolve_veto_op("learning_supersede"), "deprecate")
        self.assertEqual(_resolve_veto_op("learning_contradict"), "verify")
        self.assertEqual(_resolve_veto_op("learning_deprecate"), "verify")

    def test_resolve_veto_op_returns_none_for_unmapped_kind(self):
        # learning_verify has no defined reverse op (optimistic-immediate
        # posture) -- the command reports this rather than guessing.
        self.assertIsNone(_resolve_veto_op("learning_verify"))
        self.assertIsNone(_resolve_veto_op("something_unrecognized"))

    def test_veto_of_add_deprecates_the_row(self):
        self.assertEqual(_resolve_veto_op("learning_add"), "deprecate")
        content = "auto-integrated add to veto"
        add = self._log("--type", "pattern", "--content", content)
        self.assertEqual(add.returncode, 0, add.stderr)
        row_id = json.loads(add.stdout)["id"]
        sha = ls.content_sha256(content)

        result = self._log("deprecate", row_id, "--project", self.slug, "--expected-sha", sha)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(self._heads()[row_id]["deprecated"])

    def test_veto_of_supersede_deprecates_the_new_head(self):
        self.assertEqual(_resolve_veto_op("learning_supersede"), "deprecate")
        old_content = "pre-supersede row"
        add = self._log("--type", "pattern", "--content", old_content)
        old_id = json.loads(add.stdout)["id"]
        old_sha = ls.content_sha256(old_content)

        new_content = "post-supersede row"
        sup = self._log(
            "supersede", old_id, "--project", self.slug,
            "--content", new_content, "--expected-sha", old_sha,
        )
        self.assertEqual(sup.returncode, 0, sup.stderr)
        new_id = json.loads(sup.stdout)["id"]
        new_sha = ls.content_sha256(new_content)

        result = self._log("deprecate", new_id, "--project", self.slug, "--expected-sha", new_sha)
        self.assertEqual(result.returncode, 0, result.stderr)
        heads = self._heads()
        self.assertTrue(heads[new_id]["deprecated"])
        # The old (superseded) head is untouched by this veto -- vetoing
        # only the NEW head the supersede produced, matching "the row" the
        # dispatch table's new_entry_id resolution points at.
        self.assertFalse(heads[old_id]["deprecated"])

    def test_veto_of_contradict_re_lifts_via_verify(self):
        # Honest, code-verified claim (not assumed from plan prose):
        # verify() genuinely counteracts a contradict -- a contradiction
        # cuts confidence by a flat 1.5; reuse (uses) can add back up to a
        # capped +2.0. Assert the structural mechanics that make this true:
        # the contradiction lands, then a verify call succeeds and bumps
        # `uses` (the counter effective_confidence() reads to counteract
        # the contradiction).
        self.assertEqual(_resolve_veto_op("learning_contradict"), "verify")
        content = "row wrongly auto-contradicted"
        add = self._log("--type", "pattern", "--content", content)
        row_id = json.loads(add.stdout)["id"]

        contra = self._log("contradict", row_id, "--project", self.slug)
        self.assertEqual(contra.returncode, 0, contra.stderr)
        before = self._heads()[row_id]
        self.assertEqual(before["contradictions"], 1)
        self.assertEqual(before["uses"], 0)

        result = self._log("verify", row_id, "--project", self.slug)
        self.assertEqual(result.returncode, 0, result.stderr)
        after = self._heads()[row_id]
        self.assertEqual(after["uses"], 1)
        self.assertEqual(after["contradictions"], 1)  # verify never clears contradictions; it outweighs them

    def test_veto_of_deprecate_via_verify_succeeds_but_row_stays_deprecated(self):
        # Honest, code-verified LIMITATION (not assumed from plan prose):
        # deprecate is a hard, unconditional exclusion
        # (effective_confidence() returns 0.0 whenever deprecated is True,
        # regardless of uses) and there is no "un-deprecate" op in this
        # store's fold semantics. The documented reverse-op (verify) still
        # succeeds structurally and records the reuse signal, but it does
        # NOT restore visibility -- this test pins that exact, currently-
        # true limitation rather than asserting a restoration that the
        # store cannot actually perform.
        self.assertEqual(_resolve_veto_op("learning_deprecate"), "verify")
        content = "row wrongly auto-deprecated"
        add = self._log("--type", "pattern", "--content", content)
        row_id = json.loads(add.stdout)["id"]
        sha = ls.content_sha256(content)

        dep = self._log("deprecate", row_id, "--project", self.slug, "--expected-sha", sha)
        self.assertEqual(dep.returncode, 0, dep.stderr)
        self.assertTrue(self._heads()[row_id]["deprecated"])

        result = self._log("verify", row_id, "--project", self.slug)
        self.assertEqual(result.returncode, 0, result.stderr)
        after = self._heads()[row_id]
        self.assertEqual(after["uses"], 1)
        self.assertTrue(after["deprecated"], "no un-deprecate op exists; verify must not clear the flag")
        self.assertEqual(ls.effective_confidence(after), 0.0)

    def test_veto_deprecate_reports_cas_mismatch_on_stale_sha(self):
        # "the right exit-code handling": a stale/wrong --expected-sha
        # must surface as the documented CAS-mismatch exit code (3), never
        # silently succeed or silently fail some other way.
        content = "row for stale-sha veto attempt"
        add = self._log("--type", "pattern", "--content", content)
        row_id = json.loads(add.stdout)["id"]
        wrong_sha = ls.content_sha256("this is not the row's real content")

        result = self._log("deprecate", row_id, "--project", self.slug, "--expected-sha", wrong_sha)
        self.assertEqual(result.returncode, 3, result.stderr)
        self.assertFalse(self._heads()[row_id]["deprecated"])

    def test_veto_verify_on_missing_id_returns_exit_1(self):
        # "the right exit-code handling": a veto target that no longer
        # resolves must surface as exit 1 (target not found), not a crash
        # or a false success.
        result = self._log("verify", "doesnotexist01", "--project", self.slug)
        self.assertEqual(result.returncode, 1, result.stderr)


# ---------------------------------------------------------------------------
# ccgm-learnings-sync revert <sha>
# ---------------------------------------------------------------------------

class SyncRevertTests(unittest.TestCase):
    """Uses its OWN scratch git store per test (separate from the
    module-level _TMP the classes above share), since these tests exercise
    real git history via subprocess, not just the JSONL store."""

    def setUp(self) -> None:
        self.store_dir = Path(tempfile.mkdtemp(prefix="ccgm-dream-review-sync-"))
        self.addCleanup(shutil.rmtree, self.store_dir, ignore_errors=True)
        self.env = os.environ.copy()
        self.env["CCGM_LEARNINGS_DIR"] = str(self.store_dir)
        # Pin the writer id so shard writes land in solo.jsonl, which
        # _shard_ids reads by default. os.environ.copy() alone leaves
        # agent_id() to resolve via the ambient .env.clone of whatever clone
        # this test runs in (e.g. agent-w0-c0), writing to that shard and
        # making _shard_ids find an empty set -- the same hermetic-writer
        # convention TrustedWriterOriginBindingTests follows (never depend on
        # the host cwd/.env.clone). Proves these tests pass with NO external
        # CCGM_AGENT_ID set.
        self.env["CCGM_AGENT_ID"] = "solo"
        self.env["GIT_CONFIG_GLOBAL"] = "/dev/null"
        self.env["GIT_AUTHOR_NAME"] = "ccgm-test"
        self.env["GIT_AUTHOR_EMAIL"] = "ccgm-test@example.com"
        self.env["GIT_COMMITTER_NAME"] = "ccgm-test"
        self.env["GIT_COMMITTER_EMAIL"] = "ccgm-test@example.com"

    def _sync(self, *args: str) -> tuple[dict, subprocess.CompletedProcess]:
        proc = subprocess.run(
            [sys.executable, str(SYNC_CLI), *args],
            env=self.env, capture_output=True, text=True,
        )
        last_line = next((ln for ln in reversed(proc.stdout.splitlines()) if ln.strip()), "{}")
        return json.loads(last_line), proc

    def _log(self, *args: str, project: str) -> subprocess.CompletedProcess:
        env = dict(self.env)
        env["CCGM_LEARNINGS_PROJECT"] = project
        return subprocess.run(
            [sys.executable, str(LOG_CLI), *args],
            env=env, capture_output=True, text=True,
        )

    def _git(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["git", "-C", str(self.store_dir), *args],
            capture_output=True, text=True,
        )

    def _shard_ids(self, slug: str, writer: str = "solo") -> set[str]:
        """Read the writer's shard file directly for `slug`, under THIS
        test's own `self.store_dir` -- NOT via learnings_store.load_all(),
        which reads the module-level ls.LEARNINGS_ROOT frozen at import
        time for the OTHER test classes in this file, a different
        directory entirely from this class's own scratch git store.
        Returns the set of ids present (whatever their `op` -- add,
        supersede, verify, etc.)."""
        shard = self.store_dir / slug / "agents" / f"{writer}.jsonl"
        if not shard.is_file():
            return set()
        ids: set[str] = set()
        for line in shard.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            ids.add(json.loads(line)["id"])
        return ids

    def test_revert_undoes_exactly_that_commits_writes_store_clean_after(self):
        # The realistic case: the shard file already exists (a seed write)
        # before the commit under test, and MORE writes land after it --
        # exactly the shape a real /dream-review revert targets (an old
        # batch, reviewed days later, with other nights' writes since).
        self._sync("init")
        slug = _unique_slug("revert-mid")

        seed = self._log("--type", "pattern", "--content", "seed entry", project=slug)
        self.assertEqual(seed.returncode, 0, seed.stderr)
        self._sync("commit", "-m", "seed")

        add_a = self._log("--type", "pattern", "--content", "commit A entry", project=slug)
        self.assertEqual(add_a.returncode, 0, add_a.stderr)
        id_a = json.loads(add_a.stdout)["id"]
        out_a, _ = self._sync("commit", "-m", "commit A")
        self.assertTrue(out_a["ok"])
        self.assertEqual(out_a["action"], "committed")
        sha_a = out_a["sha"]

        add_b = self._log("--type", "pattern", "--content", "commit B entry", project=slug)
        self.assertEqual(add_b.returncode, 0, add_b.stderr)
        id_b = json.loads(add_b.stdout)["id"]
        out_b, _ = self._sync("commit", "-m", "commit B")
        self.assertTrue(out_b["ok"])

        revert_out, revert_proc = self._sync("revert", sha_a)
        self.assertEqual(revert_proc.returncode, 0, revert_out)
        self.assertTrue(revert_out["ok"])
        self.assertEqual(revert_out["action"], "reverted")
        self.assertIn(slug + "/agents/", revert_out["touched_files"][0])

        status_out, _ = self._sync("status")
        self.assertEqual(status_out["dirty_files"], 0)
        self.assertFalse(status_out["in_progress"])

        ids = self._shard_ids(slug)
        self.assertNotIn(id_a, ids, "commit A's write must be undone")
        self.assertIn(id_b, ids, "commit B's write must survive untouched")

    def test_revert_of_a_batch_commit_with_multiple_lines(self):
        # A single commit that added TWO lines to the same shard file in
        # one go (mirrors run_optimistic_integrate()'s one-commit-per-batch
        # shape), reverted after a further, unrelated write.
        self._sync("init")
        slug = _unique_slug("revert-batch")

        self._log("--type", "pattern", "--content", "batch seed", project=slug)
        self._sync("commit", "-m", "batch seed")

        b1 = self._log("--type", "pattern", "--content", "batch line one", project=slug)
        id_b1 = json.loads(b1.stdout)["id"]
        b2 = self._log("--type", "pattern", "--content", "batch line two", project=slug)
        id_b2 = json.loads(b2.stdout)["id"]
        batch_out, _ = self._sync("commit", "-m", "optbatch commit (2 writes)")
        self.assertTrue(batch_out["ok"])
        sha_batch = batch_out["sha"]

        later = self._log("--type", "pattern", "--content", "later unrelated write", project=slug)
        id_later = json.loads(later.stdout)["id"]
        self._sync("commit", "-m", "later write")

        revert_out, revert_proc = self._sync("revert", sha_batch)
        self.assertEqual(revert_proc.returncode, 0, revert_out)
        self.assertEqual(revert_out["action"], "reverted")

        ids = self._shard_ids(slug)
        self.assertNotIn(id_b1, ids)
        self.assertNotIn(id_b2, ids)
        self.assertIn(id_later, ids)

    def test_revert_of_the_file_creation_commit_after_the_file_grew(self):
        # The commit under revert is the one that CREATED the shard file
        # (its very first line); a later commit added more content to that
        # SAME file. This is the shape a naive `git apply -R` fails on
        # (the reverse patch reads as "delete the whole file", which
        # conflicts with content a later commit still needs) -- the
        # line-set-difference approach sidesteps that ambiguity entirely.
        self._sync("init")
        slug = _unique_slug("revert-fresh")

        first = self._log("--type", "pattern", "--content", "fresh file first entry", project=slug)
        id_first = json.loads(first.stdout)["id"]
        out_first, _ = self._sync("commit", "-m", "commit X (creates the file)")
        sha_first = out_first["sha"]

        second = self._log("--type", "pattern", "--content", "second entry after X", project=slug)
        id_second = json.loads(second.stdout)["id"]
        self._sync("commit", "-m", "commit Y")

        revert_out, revert_proc = self._sync("revert", sha_first)
        self.assertEqual(revert_proc.returncode, 0, revert_out)
        self.assertEqual(revert_out["action"], "reverted")

        ids = self._shard_ids(slug)
        self.assertNotIn(id_first, ids)
        self.assertIn(id_second, ids)

    def test_revert_is_idempotent_second_call_is_a_clean_noop(self):
        self._sync("init")
        slug = _unique_slug("revert-noop")
        add = self._log("--type", "pattern", "--content", "entry to revert twice", project=slug)
        out_commit, _ = self._sync("commit", "-m", "the commit")
        sha = out_commit["sha"]

        first, _ = self._sync("revert", sha)
        self.assertEqual(first["action"], "reverted")

        second, second_proc = self._sync("revert", sha)
        self.assertEqual(second_proc.returncode, 0, second)
        self.assertTrue(second["ok"])
        self.assertEqual(second["action"], "noop")

    def test_revert_of_bad_sha_fails_cleanly(self):
        self._sync("init")
        out, proc = self._sync("revert", "0000000000000000000000000000000000dead")
        self.assertEqual(proc.returncode, 1)
        self.assertFalse(out["ok"])
        self.assertEqual(out["action"], "failed")

    def test_revert_of_a_non_addition_commit_is_refused_and_store_stays_clean(self):
        # This store's own write path is append-only by construction and
        # should never produce this shape -- but a hand-edited shard or an
        # unrelated manual commit could. Refuse before touching anything.
        self._sync("init")
        slug = _unique_slug("revert-nonaddition")
        self._log("--type", "pattern", "--content", "line to be edited", project=slug)
        self._sync("commit", "-m", "seed")

        shard = self.store_dir / slug / "agents" / "solo.jsonl"
        text = shard.read_text(encoding="utf-8")
        shard.write_text(text.replace("line to be edited", "line WAS edited manually"), encoding="utf-8")
        commit_proc = self._git("commit", "-am", "manual content edit, not an append")
        self.assertEqual(commit_proc.returncode, 0, commit_proc.stderr)
        manual_sha_proc = self._git("rev-parse", "HEAD")
        manual_sha = manual_sha_proc.stdout.strip()

        out, proc = self._sync("revert", manual_sha)
        self.assertEqual(proc.returncode, 1)
        self.assertFalse(out["ok"])
        self.assertEqual(out["action"], "unsupported")

        status_out, _ = self._sync("status")
        self.assertEqual(status_out["dirty_files"], 0, "a refused revert must never leave a partial mutation")

    def test_revert_rolls_back_and_stays_clean_when_commit_fails(self):
        # Fix 4: force `git commit` to fail AFTER the shard was already
        # mutated + staged (a pre-commit hook that always rejects), and
        # assert the revert restored the shard byte-for-byte AND left a CLEAN
        # tree -- not a dirty, half-mutated, still-staged shard.
        self._sync("init")
        slug = _unique_slug("revert-rollback")
        self._log("--type", "pattern", "--content", "rollback seed", project=slug)
        self._sync("commit", "-m", "seed")
        add = self._log("--type", "pattern", "--content", "row reverted then rolled back", project=slug)
        id_a = json.loads(add.stdout)["id"]
        out_commit, _ = self._sync("commit", "-m", "commit A")
        sha = out_commit["sha"]

        shard = self.store_dir / slug / "agents" / "solo.jsonl"
        before = shard.read_text(encoding="utf-8")

        # Installed AFTER the seed/A commits: `git add` still succeeds, so the
        # revert reaches write_text()+add before the commit is rejected.
        hooks = self.store_dir / ".git" / "hooks"
        hooks.mkdir(parents=True, exist_ok=True)
        hook = hooks / "pre-commit"
        hook.write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
        hook.chmod(0o755)

        out, proc = self._sync("revert", sha)
        self.assertEqual(proc.returncode, 1)
        self.assertFalse(out["ok"])
        self.assertEqual(out["action"], "failed")

        self.assertEqual(shard.read_text(encoding="utf-8"), before, "shard must be byte-restored on rollback")
        self.assertIn(id_a, self._shard_ids(slug), "the row must survive a rolled-back revert")
        status_out, _ = self._sync("status")
        self.assertEqual(status_out["dirty_files"], 0, "a failed revert must leave a clean tree (fix 4)")

    def test_revert_refuses_on_a_dirty_working_tree(self):
        self._sync("init")
        slug = _unique_slug("revert-dirty")
        self._log("--type", "pattern", "--content", "dirty tree entry", project=slug)
        # No commit -- the tree is dirty.
        out, proc = self._sync("revert", "deadbeef")
        self.assertEqual(proc.returncode, 1)
        self.assertFalse(out["ok"])

    def test_revert_reports_blocked_when_another_git_operation_is_in_progress(self):
        self._sync("init")
        merge_head = self.store_dir / ".git" / "MERGE_HEAD"
        merge_head.write_text("deadbeef\n", encoding="utf-8")
        try:
            out, proc = self._sync("revert", "deadbeef")
            self.assertEqual(proc.returncode, 1)
            self.assertFalse(out["ok"])
            self.assertEqual(out["action"], "blocked")
        finally:
            merge_head.unlink(missing_ok=True)

    def test_revert_takes_the_shared_store_wide_sync_lock(self):
        # "MUST take the store-wide sync lock (consistent with
        # commit/pull/push)": hold the SAME lock file the other verbs use,
        # launch revert as a subprocess, and confirm it is still blocked
        # shortly after launch (a bounded wait proving a negative -- there
        # is no "became blocked" event to poll for -- per
        # systematic-debugging/condition-based-waiting's carve-out for a
        # commented, deliberate wait). Once released, the same subprocess
        # must complete promptly and successfully.
        self._sync("init")
        slug = _unique_slug("revert-lock")
        self._log("--type", "pattern", "--content", "lock test entry", project=slug)
        out_commit, _ = self._sync("commit", "-m", "the commit")
        sha = out_commit["sha"]

        lock_path = self.store_dir / ".git" / "ccgm-sync.lock"
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(str(lock_path), os.O_CREAT | os.O_RDWR, 0o644)
        fcntl.flock(fd, fcntl.LOCK_EX)
        try:
            proc = subprocess.Popen(
                [sys.executable, str(SYNC_CLI), "revert", sha],
                env=self.env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            )
            # Deliberate, commented, bounded wait (not a correctness poll):
            # proving revert is BLOCKED requires waiting some duration,
            # since there is no event to observe for "still blocked". A
            # revert of this trivial single-line file completes in single-
            # digit milliseconds once unblocked, so surviving 300ms proves
            # it is genuinely waiting on the lock, not just slow to start.
            time.sleep(0.3)
            self.assertIsNone(proc.poll(), "revert should still be blocked while the sync lock is held")
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)

        out_stdout, out_stderr = proc.communicate(timeout=10)
        self.assertEqual(proc.returncode, 0, out_stderr)
        last_line = next((ln for ln in reversed(out_stdout.splitlines()) if ln.strip()), "{}")
        result = json.loads(last_line)
        self.assertTrue(result["ok"])
        self.assertEqual(result["action"], "reverted")


class RevertCacheInvalidationTests(unittest.TestCase):
    """Fix 1 (BLOCKING): a revert SHRINKS a shard, but the read-time cache's
    incremental fast path assumed shards only grow -- so after a revert
    load_all() kept returning the reverted row AND went blind to rows added
    afterward (live-reproduced). Reproduces the exact live scenario end-to-
    end: warm the read cache with the row present, revert its commit via the
    CLI, then assert load_all() (a) no longer returns the reverted row and
    (b) sees a row added AFTER the revert.

    Defense in depth: EITHER the invalidate_cache() call OR the projection's
    shrink detection is independently sufficient, so this end-to-end test
    passes with either -- it fails only if BOTH are missing (i.e. without
    fix 1 at all). test_learnings_store.py's
    IncrementalProjectionShrinkTests isolates the projection layer on its
    own (no invalidate_cache), pinning that backstop independently.

    Reads load_all() in a FRESH subprocess pointed at this test's scratch
    store (same idiom SyncRevertTests uses for _shard_ids -- never the
    module-level ls.LEARNINGS_ROOT frozen at import for the other classes).
    The read-time snapshot cache is on-disk, so it persists across the
    separate warm/revert/read process invocations exactly as it would in
    real use."""

    def setUp(self) -> None:
        self.store_dir = Path(tempfile.mkdtemp(prefix="ccgm-dream-review-revcache-"))
        self.addCleanup(shutil.rmtree, self.store_dir, ignore_errors=True)
        # The read-cache is a sibling dir of the store (LEARNINGS_CACHE_ROOT);
        # clean it up too so a leaked snapshot never outlives the test.
        self.addCleanup(
            shutil.rmtree,
            self.store_dir.parent / (self.store_dir.name + "-cache"),
            ignore_errors=True,
        )
        self.env = os.environ.copy()
        self.env["CCGM_LEARNINGS_DIR"] = str(self.store_dir)
        self.env["CCGM_AGENT_ID"] = "solo"
        self.env["GIT_CONFIG_GLOBAL"] = "/dev/null"
        self.env["GIT_AUTHOR_NAME"] = "ccgm-test"
        self.env["GIT_AUTHOR_EMAIL"] = "ccgm-test@example.com"
        self.env["GIT_COMMITTER_NAME"] = "ccgm-test"
        self.env["GIT_COMMITTER_EMAIL"] = "ccgm-test@example.com"

    def _sync(self, *args: str) -> tuple[dict, subprocess.CompletedProcess]:
        proc = subprocess.run(
            [sys.executable, str(SYNC_CLI), *args],
            env=self.env, capture_output=True, text=True,
        )
        last_line = next((ln for ln in reversed(proc.stdout.splitlines()) if ln.strip()), "{}")
        return json.loads(last_line), proc

    def _log(self, *args: str, project: str) -> subprocess.CompletedProcess:
        env = dict(self.env)
        env["CCGM_LEARNINGS_PROJECT"] = project
        return subprocess.run(
            [sys.executable, str(LOG_CLI), *args],
            env=env, capture_output=True, text=True,
        )

    def _load_all_ids(self, slug: str) -> set[str]:
        """load_all() in a FRESH subprocess pointed (via CCGM_LEARNINGS_DIR
        in self.env) at this test's scratch store + its sibling on-disk
        cache -- the same store the sync/log CLIs mutate. This both WARMS
        (first call) and READS the persistent snapshot cache the revert CLI
        invalidates, without repointing this process's frozen
        ls.LEARNINGS_ROOT."""
        code = (
            "import json, learnings_store as ls;"
            f"print(json.dumps([e['id'] for e in ls.load_all({slug!r})]))"
        )
        env = dict(self.env)
        env["PYTHONPATH"] = str(SELF_IMPROVING_LIB)
        proc = subprocess.run(
            [sys.executable, "-c", code], env=env, capture_output=True, text=True,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return set(json.loads(proc.stdout.strip().splitlines()[-1]))

    def test_revert_drops_reverted_row_and_projection_sees_post_revert_row(self):
        self._sync("init")
        slug = _unique_slug("revcache")

        seed = self._log("--type", "pattern", "--content", "seed entry", project=slug)
        self.assertEqual(seed.returncode, 0, seed.stderr)
        self._sync("commit", "-m", "seed")

        add_a = self._log("--type", "pattern", "--content", "row A to revert", project=slug)
        self.assertEqual(add_a.returncode, 0, add_a.stderr)
        id_a = json.loads(add_a.stdout)["id"]
        out_a, _ = self._sync("commit", "-m", "commit A")
        self.assertEqual(out_a["action"], "committed")
        sha_a = out_a["sha"]

        # WARM the on-disk read-time snapshot cache with A present.
        self.assertIn(id_a, self._load_all_ids(slug))

        # Revert A's commit -- SHRINKS the shard.
        revert_out, revert_proc = self._sync("revert", sha_a)
        self.assertEqual(revert_proc.returncode, 0, revert_out)
        self.assertEqual(revert_out["action"], "reverted")

        # (a) The reverted row is gone. WITHOUT fix 1 the stale grow-only
        # cache would still return it.
        self.assertNotIn(
            id_a, self._load_all_ids(slug), "reverted row must be gone from load_all()"
        )

        # (b) A row added AFTER the revert is visible. WITHOUT fix 1 the
        # cache's overshot line watermark would skip past it.
        add_c = self._log("--type", "pattern", "--content", "row C after revert", project=slug)
        self.assertEqual(add_c.returncode, 0, add_c.stderr)
        id_c = json.loads(add_c.stdout)["id"]
        self._sync("commit", "-m", "commit C")

        ids_final = self._load_all_ids(slug)
        self.assertIn(id_c, ids_final, "row added after revert must be visible")
        self.assertNotIn(id_a, ids_final)


if __name__ == "__main__":
    unittest.main(verbosity=2)
