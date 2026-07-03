#!/usr/bin/env python3
"""
Tests for the learnings-store READ path (epic 4, issue #754):

  - modules/self-improving/bin/ccgm-learnings-search's new age/verify
    wrapper, `--format jsonl` `age_days` field, and `[anchor-missing]`
    tagging.
  - modules/self-improving/hooks/learnings-inject.py, the new opt-in,
    prefix-cache-safe SessionStart injection hook.

Runs against an isolated CCGM_LEARNINGS_DIR tempdir, never the real
~/.claude/learnings/ store.

Hermetic by design (issue #764 defense-in-depth): #764 documents a leak
where a self-improving test setUp sets CCGM_LEARNINGS_PROJECT /
CCGM_LEARNINGS_DIR without a matching tearDown restore, poisoning slug
resolution in tests that run later in the same pytest process. Fixing that
leak in test_learnings_store.py is tracked separately (#764) and is out of
scope here (that file is not touched by this change). This file protects
itself either way: every test that touches either env var goes through
HermeticEnvTestCase, which saves the pre-test value in setUp and restores
(not merely deletes) it via addCleanup, so this file can never leak into --
or be silently misled by -- a sibling test file/process.

Run with: python3 -m pytest modules/self-improving/tests/test_learnings_inject.py
"""

from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import uuid
from importlib.machinery import SourceFileLoader
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[2]

sys.path.insert(0, str(HERE.parent / "lib"))

# Isolate the store BEFORE importing learnings_store -- LEARNINGS_ROOT and
# LEARNINGS_CACHE_ROOT are module-level constants computed once at import
# time from this env var (mirrors test_learnings_store.py's own setup).
_TMP = tempfile.mkdtemp(prefix="ccgm-learnings-inject-test-")
os.environ["CCGM_LEARNINGS_DIR"] = _TMP

import learnings_store as ls  # noqa: E402

SEARCH_CLI_PATH = HERE.parent / "bin" / "ccgm-learnings-search"
INJECT_HOOK_PATH = HERE.parent / "hooks" / "learnings-inject.py"
REPO_DETECT_PATH = REPO_ROOT / "modules" / "session-history" / "scripts" / "repo_detect.py"


def _load_module(name: str, path: Path):
    # spec_from_file_location() infers the loader from the file extension,
    # which fails for extension-less scripts like ccgm-learnings-search and
    # learnings-inject.py's installed-symlink name. Building the loader
    # explicitly works regardless of the file's name/extension.
    loader = SourceFileLoader(name, str(path))
    spec = importlib.util.spec_from_loader(name, loader)
    assert spec
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


# The hook and the ccgm-learnings-search CLI are extension-less scripts; load
# them once as modules so most tests can call their functions directly
# instead of paying subprocess overhead. A handful of tests below still
# shell out via subprocess to pin the real stdin/argv/stdout contract.
hook = _load_module("learnings_inject_hook", INJECT_HOOK_PATH)
search_cli = _load_module("ccgm_learnings_search_cli", SEARCH_CLI_PATH)


class HermeticEnvTestCase(unittest.TestCase):
    """Base class: saves + restores CCGM_LEARNINGS_PROJECT, CCGM_LEARNINGS_DIR,
    and config.json around every test (issue #764 defense-in-depth). The
    config.json guard exists for the Stage-2-review regression tests below
    (budget/config-cast/conflict-render) that call `ls.save_config(...)` --
    CONFIG_PATH lives inside the SAME shared CCGM_LEARNINGS_DIR tempdir
    every test in this file runs against, so a config left behind by one
    test would otherwise leak into every test that runs after it.

    Subclasses that override setUp() must call super().setUp() FIRST (before
    mutating either var) so the pre-test value is captured accurately.
    """

    def setUp(self) -> None:
        super().setUp()
        for key in ("CCGM_LEARNINGS_PROJECT", "CCGM_LEARNINGS_DIR"):
            saved = os.environ.get(key)
            if saved is None:
                self.addCleanup(os.environ.pop, key, None)
            else:
                self.addCleanup(os.environ.__setitem__, key, saved)

        if ls.CONFIG_PATH.is_file():
            saved_config = ls.CONFIG_PATH.read_bytes()
            self.addCleanup(ls.CONFIG_PATH.write_bytes, saved_config)
        else:
            self.addCleanup(lambda: ls.CONFIG_PATH.unlink(missing_ok=True))


# ---------------------------------------------------------------------------
# ccgm-learnings-search: age/verify wrapper, age_days, anchor-missing
# ---------------------------------------------------------------------------

class SearchWrapperRenderingTests(unittest.TestCase):
    """Pure rendering-function tests -- no store I/O, no env dependence."""

    def _entry(self, **overrides) -> dict:
        base = ls.build_entry(type_="pattern", content="wrapper rendering fixture", confidence=8)
        base.update(overrides)
        return base

    def test_preamble_includes_age_wrapper(self):
        out = search_cli._render_preamble([self._entry()])
        self.assertIn("[age:", out)
        self.assertIn("verify files[] anchors before asserting", out)

    def test_markdown_includes_age_wrapper(self):
        out = search_cli._render_markdown([self._entry()])
        self.assertIn("[age:", out)
        self.assertIn("verify files[] anchors before asserting", out)

    def test_age_days_reflects_elapsed_time(self):
        e = self._entry()
        e["last_verified"] = "2020-01-01T00:00:00.000Z"
        now = ls._parse_iso("2020-01-11T00:00:00.000Z")  # exactly 10 days later
        self.assertEqual(search_cli._age_days(e, now=now), 10)

    def test_age_days_zero_for_unparseable_timestamp(self):
        e = self._entry()
        e["last_verified"] = ""
        e["timestamp"] = ""
        self.assertEqual(search_cli._age_days(e), 0)

    def test_jsonl_gains_age_days_and_nothing_else_changes(self):
        e = self._entry()
        out = search_cli._render_jsonl([e])
        parsed = json.loads(out.strip())
        self.assertIn("age_days", parsed)
        self.assertIsInstance(parsed["age_days"], int)

        original_keys = set(e.keys())
        parsed_keys = set(parsed.keys())
        self.assertEqual(parsed_keys - original_keys, {"age_days"},
                          "jsonl format must add exactly age_days, nothing else")
        self.assertEqual(original_keys - parsed_keys, set(),
                          "jsonl format must not drop any existing field")
        for k in original_keys:
            self.assertEqual(parsed[k], e[k], f"field {k!r} changed value/shape")

    def test_jsonl_empty_input_still_empty_output(self):
        self.assertEqual(search_cli._render_jsonl([]), "")

    def test_anchor_missing_tagged_when_file_gone(self):
        e = self._entry(files=["definitely/does/not/exist.py"])
        with tempfile.TemporaryDirectory() as td:
            wrapper = search_cli._verify_wrapper(e, repo_root=Path(td))
        self.assertIn("[anchor-missing]", wrapper)

    def test_anchor_present_not_tagged(self):
        with tempfile.TemporaryDirectory() as td:
            (Path(td) / "exists.py").write_text("# fixture\n", encoding="utf-8")
            e = self._entry(files=["exists.py"])
            wrapper = search_cli._verify_wrapper(e, repo_root=Path(td))
        self.assertNotIn("[anchor-missing]", wrapper)

    def test_no_files_never_tagged(self):
        e = self._entry(files=[])
        with tempfile.TemporaryDirectory() as td:
            wrapper = search_cli._verify_wrapper(e, repo_root=Path(td))
        self.assertNotIn("[anchor-missing]", wrapper)

    def test_no_repo_root_never_tagged(self):
        # has_stale_file_refs fails safe (False) when repo_root is None,
        # regardless of whether files[] is populated.
        e = self._entry(files=["some/file.py"])
        wrapper = search_cli._verify_wrapper(e, repo_root=None)
        self.assertNotIn("[anchor-missing]", wrapper)


class SearchCliSubprocessTests(HermeticEnvTestCase):
    """End-to-end: invoke the real ccgm-learnings-search script, pinning the
    literal contract the acceptance criteria exercise
    (`ccgm-learnings-search --query git --max 2`)."""

    def setUp(self):
        super().setUp()
        self.slug = f"inject-cli-{uuid.uuid4().hex[:10]}"
        os.environ["CCGM_LEARNINGS_PROJECT"] = self.slug
        e = ls.build_entry(
            type_="pattern", content="git branch workflow fixture learning",
            tags=["git"], confidence=8,
        )
        ls.append_entry(e)

    def tearDown(self):
        shutil.rmtree(ls.project_dir(self.slug), ignore_errors=True)
        shutil.rmtree(ls._cache_dir(self.slug), ignore_errors=True)
        super().tearDown()

    def _env(self):
        env = os.environ.copy()
        env["CCGM_LEARNINGS_PROJECT"] = self.slug
        # Pin to the store dir THIS process actually bound at import time
        # (ls.LEARNINGS_ROOT), never the raw os.environ value: if a sibling
        # test file (e.g. test_learnings_store.py) is collected in the same
        # pytest run and reassigns CCGM_LEARNINGS_DIR at ITS OWN module
        # level, os.environ ends up holding whichever file's assignment ran
        # last while ls.LEARNINGS_ROOT stays bound to whichever file
        # imported learnings_store FIRST (import caching) -- the two can
        # diverge. Spawning a subprocess with the stale env value would
        # silently query an empty, unrelated directory (issue #764's class
        # of bug, manifesting through CCGM_LEARNINGS_DIR instead of
        # CCGM_LEARNINGS_PROJECT). Pinning to ls.LEARNINGS_ROOT directly
        # makes this test immune to collection order.
        env["CCGM_LEARNINGS_DIR"] = str(ls.LEARNINGS_ROOT)
        return env

    def test_cli_preamble_output_shows_age_wrapper(self):
        result = subprocess.run(
            [sys.executable, str(SEARCH_CLI_PATH), "--query", "git", "--max", "2"],
            env=self._env(), capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("[age:", result.stdout)
        self.assertIn("verify files[] anchors before asserting", result.stdout)

    def test_cli_jsonl_output_shape(self):
        result = subprocess.run(
            [sys.executable, str(SEARCH_CLI_PATH), "--query", "git", "--format", "jsonl"],
            env=self._env(), capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        rows = [json.loads(line) for line in result.stdout.strip().splitlines()]
        self.assertTrue(rows)
        self.assertIn("age_days", rows[0])


class SearchCliConflictRenderingTests(HermeticEnvTestCase):
    """adrev-011 half (b): unlike the SessionStart injection path (which
    suppresses conflicted rows outright, hooks/learnings-inject.py), the
    search CLI must render a visible marker on a conflicted row -- a human
    running this CLI directly should see the conflict, not have it silently
    hidden as if it were settled truth. Same fixture technique as
    ConflictSuppressionTests below (two independent supersedes on the same
    target -> conflict: true on both live heads)."""

    def setUp(self):
        super().setUp()
        self.slug = f"search-conflict-{uuid.uuid4().hex[:10]}"
        os.environ["CCGM_LEARNINGS_PROJECT"] = self.slug
        os.environ.pop("CCGM_AGENT_ID", None)

        contested = ls.build_entry(type_="pattern", content="contested cli-render learning", confidence=9)
        ls.append_entry(contested)
        self.old_id = contested["id"]
        ls.supersede_entry(self.old_id, content="conflicted cli branch A", slug=self.slug)
        ls.supersede_entry(self.old_id, content="conflicted cli branch B", slug=self.slug)

    def tearDown(self):
        shutil.rmtree(ls.project_dir(self.slug), ignore_errors=True)
        shutil.rmtree(ls._cache_dir(self.slug), ignore_errors=True)
        os.environ.pop("CCGM_AGENT_ID", None)
        super().tearDown()

    def _conflicted_rows(self) -> list[dict]:
        rows = [r for r in ls.search(slug=self.slug) if r.get("conflict")]
        self.assertEqual(len(rows), 2, "fixture setup should yield exactly 2 live conflicting heads")
        return rows

    def test_verify_wrapper_tags_conflicted_row(self):
        wrapper = search_cli._verify_wrapper(self._conflicted_rows()[0])
        self.assertIn("[conflict: competing heads", wrapper)
        self.assertIn("not settled", wrapper)

    def test_verify_wrapper_does_not_tag_clean_row(self):
        clean = ls.build_entry(type_="pattern", content="clean cli-render learning", confidence=9)
        wrapper = search_cli._verify_wrapper(clean)
        self.assertNotIn("[conflict:", wrapper)

    def test_preamble_shows_conflict_tag(self):
        out = search_cli._render_preamble(self._conflicted_rows())
        self.assertIn("[conflict: competing heads", out)

    def test_markdown_shows_conflict_tag(self):
        out = search_cli._render_markdown(self._conflicted_rows())
        self.assertIn("[conflict: competing heads", out)

    def test_cli_subprocess_shows_conflict_tag_and_does_not_suppress(self):
        env = os.environ.copy()
        env["CCGM_LEARNINGS_DIR"] = str(ls.LEARNINGS_ROOT)
        result = subprocess.run(
            [sys.executable, str(SEARCH_CLI_PATH), "--project", self.slug, "--max", "10"],
            env=env, capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("[conflict: competing heads", result.stdout)
        # Do NOT suppress: unlike the SessionStart injection path, a human
        # running the CLI directly should still see both competing heads.
        self.assertIn("conflicted cli branch A", result.stdout)
        self.assertIn("conflicted cli branch B", result.stdout)

    def test_jsonl_still_carries_conflict_field(self):
        rows = self._conflicted_rows()
        out = search_cli._render_jsonl(rows)
        parsed = [json.loads(line) for line in out.strip().splitlines()]
        self.assertEqual(len(parsed), 2)
        for row in parsed:
            self.assertTrue(row.get("conflict"))


# ---------------------------------------------------------------------------
# learnings-inject.py: opt-in gate, budget, ordering, conflict suppression
# ---------------------------------------------------------------------------

class TruthyTests(unittest.TestCase):
    def test_truthy_values(self):
        self.assertTrue(hook._truthy("true"))
        self.assertTrue(hook._truthy("TRUE"))
        self.assertTrue(hook._truthy("1"))
        self.assertTrue(hook._truthy("yes"))

    def test_falsy_values(self):
        self.assertFalse(hook._truthy("false"))
        self.assertFalse(hook._truthy("0"))
        self.assertFalse(hook._truthy(None))
        self.assertFalse(hook._truthy(""))


class BuildContextGateTests(HermeticEnvTestCase):
    def setUp(self):
        super().setUp()
        self.slug = f"inject-gate-{uuid.uuid4().hex[:10]}"
        os.environ["CCGM_LEARNINGS_PROJECT"] = self.slug
        ls.append_entry(ls.build_entry(type_="pattern", content="gate fixture learning", confidence=9))

    def tearDown(self):
        shutil.rmtree(ls.project_dir(self.slug), ignore_errors=True)
        shutil.rmtree(ls._cache_dir(self.slug), ignore_errors=True)
        super().tearDown()

    def test_silent_when_flag_unset(self):
        self.assertIsNone(hook.build_context({"source": "startup", "cwd": os.getcwd()}, env={}))

    def test_silent_when_flag_false(self):
        self.assertIsNone(
            hook.build_context({"source": "startup", "cwd": os.getcwd()}, env={"CCGM_LEARNINGS_INJECT": "false"})
        )

    def test_emits_block_when_flag_true(self):
        block = hook.build_context(
            {"source": "startup", "cwd": os.getcwd()}, env={"CCGM_LEARNINGS_INJECT": "true"}
        )
        self.assertIsNotNone(block)
        self.assertIn("<ccgm-learnings-injection>", block)
        self.assertIn("</ccgm-learnings-injection>", block)
        self.assertIn("gate fixture learning", block)


class HookSubprocessTests(HermeticEnvTestCase):
    """End-to-end: the literal stdin/env contract from the acceptance
    criteria (`echo '{"source":"startup"}' | CCGM_LEARNINGS_INJECT=true
    python3 .../learnings-inject.py`)."""

    def setUp(self):
        super().setUp()
        self.slug = f"inject-subproc-{uuid.uuid4().hex[:10]}"
        os.environ["CCGM_LEARNINGS_PROJECT"] = self.slug
        ls.append_entry(ls.build_entry(type_="pattern", content="subprocess visible learning", confidence=8))

    def tearDown(self):
        shutil.rmtree(ls.project_dir(self.slug), ignore_errors=True)
        shutil.rmtree(ls._cache_dir(self.slug), ignore_errors=True)
        super().tearDown()

    def _env(self, **extra):
        env = os.environ.copy()
        env["CCGM_LEARNINGS_PROJECT"] = self.slug
        # See SearchCliSubprocessTests._env() for why this is pinned to the
        # actually-bound ls.LEARNINGS_ROOT rather than trusted from
        # os.environ (issue #764-class collection-order hazard).
        env["CCGM_LEARNINGS_DIR"] = str(ls.LEARNINGS_ROOT)
        env.pop("CCGM_LEARNINGS_INJECT", None)
        env.update(extra)
        return env

    def _run(self, source: str, **extra_env) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(INJECT_HOOK_PATH)],
            input=json.dumps({"source": source, "cwd": os.getcwd()}),
            env=self._env(**extra_env),
            capture_output=True, text=True,
        )

    def test_prints_block_when_flag_set(self):
        result = self._run("startup", CCGM_LEARNINGS_INJECT="true")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("ccgm-learnings-injection", result.stdout)
        self.assertIn("subprocess visible learning", result.stdout)

    def test_silent_without_flag(self):
        result = self._run("startup")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "")

    def test_silent_on_non_startup_sources_even_with_flag(self):
        for source in ("resume", "compact"):
            with self.subTest(source=source):
                result = self._run(source, CCGM_LEARNINGS_INJECT="true")
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout, "", f"expected no-op for source={source!r}")

    def test_malformed_stdin_never_crashes(self):
        result = subprocess.run(
            [sys.executable, str(INJECT_HOOK_PATH)],
            input="not json{{{",
            env=self._env(CCGM_LEARNINGS_INJECT="true"),
            capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        # No "source" survives a parse failure -> falls through the
        # startup-only gate -> silent, same as any other non-startup call.
        self.assertEqual(result.stdout, "")


class SelectForInjectionBudgetTests(HermeticEnvTestCase):
    def setUp(self):
        super().setUp()
        self.slug = f"inject-budget-{uuid.uuid4().hex[:10]}"
        os.environ["CCGM_LEARNINGS_PROJECT"] = self.slug
        for i in range(6):
            e = ls.build_entry(
                type_="pattern",
                content=f"budget test learning number {i} " + ("x" * 60),
                confidence=9,
            )
            ls.append_entry(e)

    def tearDown(self):
        shutil.rmtree(ls.project_dir(self.slug), ignore_errors=True)
        shutil.rmtree(ls._cache_dir(self.slug), ignore_errors=True)
        super().tearDown()

    def test_partial_selection_under_tight_budget(self):
        # A 200-token (800-char) budget with 6 sizeable entries should
        # select some but not all -- a genuine partial cap, not an
        # all-or-nothing budget. (The envelope alone costs ~352 real chars
        # for this fixture, and each real entry ~195 -- a budget much
        # smaller than 800 would be consumed entirely by the envelope
        # reservation and legitimately select zero; see
        # BuildContextTokenBudgetTests below for the actual
        # budget-compliance regression assertion, which checks the real
        # observable len(build_context(...)) rather than recomputing the
        # code's own internal estimate here.)
        selected = hook._select_for_injection(self.slug, max_results=6, token_budget=200)
        self.assertGreater(len(selected), 0)
        self.assertLess(len(selected), 6)

    def test_respects_max_results_cap(self):
        selected = hook._select_for_injection(self.slug, max_results=2, token_budget=2000)
        self.assertLessEqual(len(selected), 2)

    def test_generous_budget_returns_all(self):
        selected = hook._select_for_injection(self.slug, max_results=8, token_budget=2000)
        self.assertEqual(len(selected), 6)

    def test_max_results_zero_returns_empty(self):
        # Stage-2 review, Recommend: the old loop appended before checking
        # the cap, so max_results=0 returned exactly 1 entry instead of 0.
        selected = hook._select_for_injection(self.slug, max_results=0, token_budget=2000)
        self.assertEqual(selected, [])

    def test_max_results_negative_returns_empty(self):
        selected = hook._select_for_injection(self.slug, max_results=-1, token_budget=2000)
        self.assertEqual(selected, [])


class BuildContextTokenBudgetTests(HermeticEnvTestCase):
    """Regression guard for the Stage-2 budget-overflow finding: the OLD
    per-entry estimate (`len(content) + 80`) did not know about the second
    (verify-wrapper) rendered line per entry, nor about the header/footer
    envelope, and drifted 129-136% over the configured budget under
    realistic (non-default) configs -- while the one test meant to catch it
    recomputed that same broken estimate and could never fail. The only
    assertion that actually proves the invariant is on build_context()'s
    real, observable output length -- never an internal estimate.

    60 entries (bigger than SelectForInjectionBudgetTests' 6-entry fixture)
    so that at max_results=100/token_budget=2000 the token budget -- not
    entry-count scarcity or the cap -- is genuinely the binding constraint,
    same as it would be for a real, well-populated store.
    """

    def setUp(self):
        super().setUp()
        self.slug = f"inject-real-budget-{uuid.uuid4().hex[:10]}"
        os.environ["CCGM_LEARNINGS_PROJECT"] = self.slug
        for i in range(60):
            e = ls.build_entry(
                type_="pattern",
                content=f"real budget regression fixture entry number {i} " + ("x" * 60),
                confidence=9,
            )
            ls.append_entry(e)

    def tearDown(self):
        shutil.rmtree(ls.project_dir(self.slug), ignore_errors=True)
        shutil.rmtree(ls._cache_dir(self.slug), ignore_errors=True)
        super().tearDown()

    def test_build_context_never_exceeds_configured_budget(self):
        # The exact two (max_results, token_budget) configs the Stage-2
        # review reproduced overflow with (129% and 136% of budget
        # respectively, against an independently-sized store).
        for max_results, token_budget in ((100, 2000), (8, 300)):
            with self.subTest(max_results=max_results, token_budget=token_budget):
                ls.save_config({"max_results": max_results, "token_budget": token_budget})
                block = hook.build_context(
                    {"source": "startup", "cwd": os.getcwd()},
                    env={"CCGM_LEARNINGS_INJECT": "true"},
                )
                self.assertIsNotNone(block, "expected at least one entry to fit the budget")
                self.assertLessEqual(len(block), token_budget * 4)


class ConfigCastGuardTests(HermeticEnvTestCase):
    """Stage-2 review Blocking #2: a syntactically-valid but
    semantically-wrong-typed config.json (max_results/token_budget as a
    string, or null) crashed the hook with an unhandled ValueError/TypeError
    from the raw int() casts -- directly contradicting this file's own
    "never raises" safety claim. Uses an EMPTY store so the assertion
    isolates the crash-safety property (exit 0, no stderr, no stdout) from
    selection correctness -- with nothing in the store to select, "prints
    nothing" is the expected output regardless of which fallback default
    the guard resolves to.
    """

    def setUp(self):
        super().setUp()
        self.slug = f"inject-badconfig-{uuid.uuid4().hex[:10]}"
        os.environ["CCGM_LEARNINGS_PROJECT"] = self.slug

    def tearDown(self):
        shutil.rmtree(ls.project_dir(self.slug), ignore_errors=True)
        shutil.rmtree(ls._cache_dir(self.slug), ignore_errors=True)
        super().tearDown()

    def _run(self) -> subprocess.CompletedProcess:
        env = os.environ.copy()
        env["CCGM_LEARNINGS_PROJECT"] = self.slug
        env["CCGM_LEARNINGS_DIR"] = str(ls.LEARNINGS_ROOT)
        env["CCGM_LEARNINGS_INJECT"] = "true"
        return subprocess.run(
            [sys.executable, str(INJECT_HOOK_PATH)],
            input=json.dumps({"source": "startup", "cwd": os.getcwd()}),
            env=env, capture_output=True, text=True,
        )

    def test_max_results_wrong_type_never_crashes(self):
        ls.save_config({"max_results": "not-a-number", "token_budget": 2000})
        result = self._run()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, "")
        self.assertEqual(result.stdout, "")

    def test_max_results_null_never_crashes(self):
        ls.save_config({"max_results": None, "token_budget": 2000})
        result = self._run()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, "")
        self.assertEqual(result.stdout, "")

    def test_token_budget_wrong_type_never_crashes(self):
        ls.save_config({"max_results": 8, "token_budget": "not-a-number"})
        result = self._run()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, "")
        self.assertEqual(result.stdout, "")


class FilesFieldCrashGuardTests(HermeticEnvTestCase):
    """Stage-2 review Blocking #2 (second reachable path): files[] elements
    are supposed to be strings, but learnings_store.validate_entry() only
    checks list-ness, not element type, so
    learnings_store.build_entry(..., files=[123]) writes successfully
    through the store's own public API and only crashes later, at read
    time, inside has_stale_file_refs(). The hook must tolerate this (skip
    the bad element, don't crash) and must not let one bad entry suppress
    its well-formed siblings from the same injected block.
    """

    def setUp(self):
        super().setUp()
        self.slug = f"inject-badfiles-{uuid.uuid4().hex[:10]}"
        os.environ["CCGM_LEARNINGS_PROJECT"] = self.slug
        bad = ls.build_entry(
            type_="pattern", content="entry with non-string files element", confidence=9, files=[123],
        )
        ls.append_entry(bad)
        ls.append_entry(ls.build_entry(type_="pattern", content="clean sibling entry", confidence=9))

    def tearDown(self):
        shutil.rmtree(ls.project_dir(self.slug), ignore_errors=True)
        shutil.rmtree(ls._cache_dir(self.slug), ignore_errors=True)
        super().tearDown()

    def test_non_string_files_element_never_crashes_and_still_injects_siblings(self):
        env = os.environ.copy()
        env["CCGM_LEARNINGS_PROJECT"] = self.slug
        env["CCGM_LEARNINGS_DIR"] = str(ls.LEARNINGS_ROOT)
        env["CCGM_LEARNINGS_INJECT"] = "true"
        result = subprocess.run(
            [sys.executable, str(INJECT_HOOK_PATH)],
            input=json.dumps({"source": "startup", "cwd": os.getcwd()}),
            env=env, capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, "")
        self.assertIn("entry with non-string files element", result.stdout)
        self.assertIn("clean sibling entry", result.stdout)


class OrderingStabilityTests(HermeticEnvTestCase):
    def setUp(self):
        super().setUp()
        self.slug = f"inject-order-{uuid.uuid4().hex[:10]}"
        os.environ["CCGM_LEARNINGS_PROJECT"] = self.slug
        for conf in (9, 7, 5):
            e = ls.build_entry(type_="pattern", content=f"ordering fixture confidence {conf}", confidence=conf)
            ls.append_entry(e)

    def tearDown(self):
        shutil.rmtree(ls.project_dir(self.slug), ignore_errors=True)
        shutil.rmtree(ls._cache_dir(self.slug), ignore_errors=True)
        super().tearDown()

    def test_two_invocations_produce_byte_identical_output(self):
        hook_input = {"source": "startup", "cwd": os.getcwd()}
        env = {"CCGM_LEARNINGS_INJECT": "true"}
        first = hook.build_context(hook_input, env)
        second = hook.build_context(hook_input, env)
        self.assertIsNotNone(first)
        self.assertEqual(first, second)


class ConflictSuppressionTests(HermeticEnvTestCase):
    """adrev-011: a row with two live competing supersedes must never reach
    the injected block as if it were settled truth."""

    def setUp(self):
        super().setUp()
        self.slug = f"inject-conflict-{uuid.uuid4().hex[:10]}"
        os.environ["CCGM_LEARNINGS_PROJECT"] = self.slug
        os.environ.pop("CCGM_AGENT_ID", None)

        clean = ls.build_entry(type_="pattern", content="clean unconflicted learning", confidence=9)
        ls.append_entry(clean)

        contested = ls.build_entry(type_="pattern", content="contested original learning", confidence=9)
        ls.append_entry(contested)
        self.old_id = contested["id"]
        # Two independent supersedes on the same target -> conflict (mirrors
        # test_learnings_store.py's ConflictTests technique exactly).
        ls.supersede_entry(self.old_id, content="conflicted branch A content", slug=self.slug)
        ls.supersede_entry(self.old_id, content="conflicted branch B content", slug=self.slug)

    def tearDown(self):
        shutil.rmtree(ls.project_dir(self.slug), ignore_errors=True)
        shutil.rmtree(ls._cache_dir(self.slug), ignore_errors=True)
        os.environ.pop("CCGM_AGENT_ID", None)
        super().tearDown()

    def test_conflicted_rows_excluded_from_injected_block(self):
        # Sanity: default search() (which _select_for_injection fetches
        # from) already hides the old, now-superseded head via the
        # pre-existing superseded_by filter, but still carries the conflict
        # flag on BOTH live competing heads it returns (Epic 1's contract
        # this test depends on -- mirrors test_learnings_store.py's own
        # test_conflict_flag_survives_into_default_search_results).
        conflicted = [r for r in ls.search(slug=self.slug) if r.get("conflict")]
        self.assertEqual(len(conflicted), 2)

        block = hook.build_context(
            {"source": "startup", "cwd": os.getcwd()}, env={"CCGM_LEARNINGS_INJECT": "true"}
        )
        self.assertIsNotNone(block)
        self.assertIn("clean unconflicted learning", block)
        self.assertNotIn("conflicted branch A content", block)
        self.assertNotIn("conflicted branch B content", block)

    def test_select_for_injection_excludes_conflicts_directly(self):
        selected = hook._select_for_injection(self.slug, max_results=8, token_budget=2000)
        contents = [e.get("content", "") for e in selected]
        self.assertIn("clean unconflicted learning", contents)
        self.assertNotIn("conflicted branch A content", contents)
        self.assertNotIn("conflicted branch B content", contents)


class SlugAgreementTests(HermeticEnvTestCase):
    """arch-1 regression guard: the hook must resolve project slugs via
    learnings_store.detect_project_slug() -- never session-history's
    repo_detect.py, whose bare-repo-name output is a different, incompatible
    slug space."""

    def test_hook_slug_matches_detect_project_slug_for_real_repo(self):
        # Exercise the real git-remote-derived path, not the env override.
        os.environ.pop("CCGM_LEARNINGS_PROJECT", None)

        # A synthetic, well-known example identity (GitHub's own placeholder
        # mascot account) -- never the maintainer's real username/repo,
        # which tests/test-no-personal-data.sh unconditionally rejects.
        fixture_repo = tempfile.mkdtemp(prefix="ccgm-fixture-repo-")
        self.addCleanup(shutil.rmtree, fixture_repo, ignore_errors=True)
        subprocess.run(["git", "init", "-q"], cwd=fixture_repo, check=True)
        subprocess.run(
            ["git", "remote", "add", "origin", "https://github.com/octocat/hello-world.git"],
            cwd=fixture_repo, check=True,
        )

        expected = ls.detect_project_slug(fixture_repo)
        # Pin the concrete value (not just "not None") so this assertion is
        # not vacuous if detect_project_slug's algorithm drifts.
        self.assertEqual(expected, "octocat-hello-world")

        hook_slug = hook.resolve_slug(fixture_repo)
        self.assertEqual(hook_slug, expected)

        # Strengthen the guard: repo_detect.py answers a DIFFERENT question
        # and returns a DIFFERENT string for this exact fixture -- if a
        # future change swapped the hook onto repo_detect.py by mistake,
        # hook_slug would become "hello-world" and the assertion above
        # would already fail. Confirm the two really do disagree here so
        # this test is not silently vacuous.
        repo_detect = _load_module("repo_detect_fixture", REPO_DETECT_PATH)
        self.assertEqual(repo_detect.detect_repo(fixture_repo), "hello-world")
        self.assertNotEqual(repo_detect.detect_repo(fixture_repo), hook_slug)


class InjectionTelemetryTests(HermeticEnvTestCase):
    """#781: after emitting the injected block, the hook appends ONE
    best-effort telemetry record (memory IDs + counts + a token estimate
    ONLY, never memory content) to a per-machine JSONL under
    CCGM_DREAMING_DIR. The write is a pure side-channel: it must never alter
    the injected stdout bytes, never block injection, and never raise -- and
    must write nothing when injection did not run.
    """

    def setUp(self):
        super().setUp()
        self.slug = f"inject-telem-{uuid.uuid4().hex[:10]}"
        os.environ["CCGM_LEARNINGS_PROJECT"] = self.slug

        # Isolate the telemetry log dir into a tempdir (restored after) so a
        # test can never touch the real ~/.claude/dreaming/injection-log/.
        self._dreaming_dir = tempfile.mkdtemp(prefix="ccgm-injection-log-test-")
        saved_dreaming = os.environ.get("CCGM_DREAMING_DIR")
        os.environ["CCGM_DREAMING_DIR"] = self._dreaming_dir
        if saved_dreaming is None:
            self.addCleanup(os.environ.pop, "CCGM_DREAMING_DIR", None)
        else:
            self.addCleanup(os.environ.__setitem__, "CCGM_DREAMING_DIR", saved_dreaming)
        self.addCleanup(shutil.rmtree, self._dreaming_dir, ignore_errors=True)

        # main()'s in-process path reads the flag from os.environ;
        # HermeticEnvTestCase only saves PROJECT/DIR, so manage INJECT here.
        saved_flag = os.environ.get("CCGM_LEARNINGS_INJECT")
        if saved_flag is None:
            self.addCleanup(os.environ.pop, "CCGM_LEARNINGS_INJECT", None)
        else:
            self.addCleanup(os.environ.__setitem__, "CCGM_LEARNINGS_INJECT", saved_flag)

        self.n = 4
        # DISTINCT confidences -> a TOTAL ranking order, so search()/selection
        # is stable across the two separate builds a byte-stability/record test
        # compares. Tied confidences expose a pre-existing store
        # snapshot-cache read-order artifact (two builds straddling cache
        # materialization can reorder tied heads) that has nothing to do with
        # telemetry -- OrderingStabilityTests uses distinct confidences for
        # exactly this reason.
        for i in range(self.n):
            ls.append_entry(ls.build_entry(
                type_="pattern",
                content=f"telemetry fixture learning number {i}",
                confidence=9 - i,
            ))

    def tearDown(self):
        shutil.rmtree(ls.project_dir(self.slug), ignore_errors=True)
        shutil.rmtree(ls._cache_dir(self.slug), ignore_errors=True)
        super().tearDown()

    def _payload(self, **extra) -> dict:
        p = {"source": "startup", "cwd": os.getcwd(), "session_id": "sess-telem-1"}
        p.update(extra)
        return p

    def _run_main(self, payload: dict) -> str:
        """Drive the real main() in-process: feed `payload` on stdin, capture
        and return stdout. Used both for the happy path and (with the append
        helper patched to raise) for the fail-safe path -- the only way to
        force file_locked_append to raise is in-process."""
        buf = io.StringIO()
        saved_stdin = sys.stdin
        sys.stdin = io.StringIO(json.dumps(payload))
        try:
            with contextlib.redirect_stdout(buf):
                hook.main()
        finally:
            sys.stdin = saved_stdin
        return buf.getvalue()

    def _read_records(self) -> "list[dict]":
        log_dir = Path(self._dreaming_dir) / "injection-log"
        if not log_dir.is_dir():
            return []
        records: "list[dict]" = []
        for f in sorted(log_dir.glob("*.jsonl")):  # glob avoids a midnight-UTC date assumption
            for line in f.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    records.append(json.loads(line))
        return records

    # -- record shape / counts / ids / tokens ------------------------------

    def test_injection_writes_exactly_one_record_with_correct_fields(self):
        os.environ["CCGM_LEARNINGS_INJECT"] = "true"
        payload = self._payload()

        # The control build also tells us the exact selected set + token
        # estimate the record must match (reused, never re-queried).
        context, selected, slug = hook._build_injection(payload, env=os.environ)
        self.assertIsNotNone(context)
        self.assertEqual(len(selected), self.n)

        self._run_main(payload)
        records = self._read_records()
        self.assertEqual(len(records), 1, "exactly one record per injection")

        rec = records[0]
        self.assertEqual(
            set(rec.keys()),
            {"timestamp", "session_id", "source", "project_slug",
             "injected_count", "injected_ids", "approx_tokens"},
        )
        self.assertEqual(rec["session_id"], "sess-telem-1")
        self.assertEqual(rec["source"], "startup")
        self.assertEqual(rec["project_slug"], slug)
        self.assertEqual(rec["injected_count"], self.n)
        self.assertEqual(rec["injected_ids"], [e["id"] for e in selected])
        self.assertEqual(len(rec["injected_ids"]), rec["injected_count"])
        self.assertEqual(rec["approx_tokens"], len(context) // hook.CHARS_PER_TOKEN)

    def test_record_never_contains_memory_content(self):
        os.environ["CCGM_LEARNINGS_INJECT"] = "true"
        payload = self._payload()
        _context, selected, _slug = hook._build_injection(payload, env=os.environ)

        self._run_main(payload)
        log_dir = Path(self._dreaming_dir) / "injection-log"
        raw = "\n".join(f.read_text(encoding="utf-8") for f in log_dir.glob("*.jsonl"))
        self.assertTrue(raw.strip())
        for e in selected:
            self.assertNotIn(
                e["content"], raw,
                "memory content must NEVER be copied into the telemetry log (issue #781)",
            )

    def test_log_path_is_outside_the_synced_learnings_store(self):
        path = str(hook._injection_log_path())
        self.assertIn("injection-log", path)
        # The synced store root must never contain the telemetry log.
        self.assertNotIn(str(ls.LEARNINGS_ROOT), path)

    def test_subprocess_end_to_end_writes_record(self):
        env = os.environ.copy()
        env["CCGM_LEARNINGS_PROJECT"] = self.slug
        # See SearchCliSubprocessTests._env() for why DIR is pinned to the
        # actually-bound ls.LEARNINGS_ROOT (issue #764 collection-order hazard).
        env["CCGM_LEARNINGS_DIR"] = str(ls.LEARNINGS_ROOT)
        env["CCGM_DREAMING_DIR"] = self._dreaming_dir
        env["CCGM_LEARNINGS_INJECT"] = "true"
        result = subprocess.run(
            [sys.executable, str(INJECT_HOOK_PATH)],
            input=json.dumps(self._payload()),
            env=env, capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("ccgm-learnings-injection", result.stdout)
        records = self._read_records()
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["injected_count"], self.n)
        self.assertEqual(records[0]["session_id"], "sess-telem-1")

    # -- fail-safe ---------------------------------------------------------

    def test_forced_telemetry_failure_still_emits_and_never_raises(self):
        os.environ["CCGM_LEARNINGS_INJECT"] = "true"
        payload = self._payload()
        control = hook.build_context(payload, env=os.environ)
        self.assertIsNotNone(control)

        with mock.patch.object(
            hook.hook_utils, "file_locked_append",
            side_effect=RuntimeError("disk on fire"),
        ):
            # Must NOT raise, and stdout must be byte-identical to the control.
            out = self._run_main(payload)
        self.assertEqual(out, control)
        # And nothing was written (the append was forced to fail).
        self.assertEqual(self._read_records(), [])

    # -- inert -------------------------------------------------------------

    def test_no_record_when_flag_unset(self):
        os.environ.pop("CCGM_LEARNINGS_INJECT", None)
        out = self._run_main(self._payload())
        self.assertEqual(out, "")
        self.assertEqual(self._read_records(), [])

    def test_no_record_when_zero_memories_selected(self):
        os.environ["CCGM_LEARNINGS_INJECT"] = "true"
        # Point at an empty slug so selection yields nothing (inert path).
        empty_slug = f"inject-telem-empty-{uuid.uuid4().hex[:10]}"
        os.environ["CCGM_LEARNINGS_PROJECT"] = empty_slug
        self.addCleanup(shutil.rmtree, ls.project_dir(empty_slug), ignore_errors=True)
        self.addCleanup(shutil.rmtree, ls._cache_dir(empty_slug), ignore_errors=True)

        out = self._run_main(self._payload())
        self.assertEqual(out, "")
        self.assertEqual(self._read_records(), [])

    # -- byte-stability ----------------------------------------------------

    def test_injected_stdout_bytes_identical_with_telemetry_vs_control(self):
        os.environ["CCGM_LEARNINGS_INJECT"] = "true"
        payload = self._payload()
        # Control: the pure injected block (build_context never logs telemetry).
        control = hook.build_context(payload, env=os.environ)
        self.assertIsNotNone(control)
        # Full main() path DOES write telemetry -- its stdout must still be
        # byte-identical to the control.
        out = self._run_main(payload)
        self.assertEqual(out, control)
        # Sanity: telemetry really did fire (otherwise this would vacuously
        # compare two telemetry-free runs).
        self.assertEqual(len(self._read_records()), 1)


def _cleanup():
    shutil.rmtree(_TMP, ignore_errors=True)
    shutil.rmtree(ls.LEARNINGS_CACHE_ROOT, ignore_errors=True)


if __name__ == "__main__":
    try:
        unittest.main(verbosity=2, exit=False)
    finally:
        _cleanup()
