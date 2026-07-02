#!/usr/bin/env python3
"""
Tests for modules/dreaming/lib/transcript_miner.py.

Runs in isolation: never touches ~/.claude/projects/ or ~/.claude/dreaming/
(watermark tests redirect CCGM_DREAMING_DIR to a tempdir; discover() tests
pass an explicit projects_root; the slug-agreement test builds its own
throwaway git repo under a tempdir).

All fixture JSONL content under tests/fixtures/ is 100% hand-authored --
never captured from a real transcript, a real API response, or the
operator's real learnings store (sec-10).

Run with: python3 -m pytest modules/dreaming/tests/test_transcript_miner.py -q
      or: python3 modules/dreaming/tests/test_transcript_miner.py
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
FIXTURES = HERE / "fixtures"
sys.path.insert(0, str(HERE.parent / "lib"))

import transcript_miner as tm  # noqa: E402

# transcript_miner's own cross-module import machinery resolves this the
# same way transcript_miner.py does (repo-relative fallback), so we can
# reuse the already-imported module rather than re-deriving the path.
detect_project_slug = tm.detect_project_slug


def _fixture(name: str) -> Path:
    return FIXTURES / name


class MineFrictionTests(unittest.TestCase):
    def test_friction_fixture_counts_and_kinds(self):
        mined = tm.mine(_fixture("friction.jsonl"))
        kinds = [e["kind"] for e in mined["friction_events"]]
        self.assertEqual(len(mined["friction_events"]), 3)
        self.assertEqual(set(kinds), {"tool_error", "hook_error", "prevented_continuation"})
        self.assertEqual(mined["tool_use_count"], 1)
        self.assertGreater(mined["friction_field_presence"], 0)

    def test_friction_fixture_pr_link_extraction(self):
        mined = tm.mine(_fixture("friction.jsonl"))
        self.assertEqual(len(mined["pr_links"]), 1)
        link = mined["pr_links"][0]
        self.assertEqual(link["pr_number"], 9001)
        self.assertEqual(link["pr_repository"], "fixtureorg/widget-app")

    def test_clean_fixture_zero_friction(self):
        mined = tm.mine(_fixture("clean.jsonl"))
        self.assertEqual(mined["friction_events"], [])
        # Fields WERE present (is_error: false, hookErrors: []) -- this is
        # "quiet", not "unrecognized". Distinguishes from drift.
        self.assertGreater(mined["friction_field_presence"], 0)
        self.assertEqual(mined["tool_use_count"], 1)

    def test_cache_read_ratio_computed(self):
        mined = tm.mine(_fixture("clean.jsonl"))
        totals = mined["token_totals"]
        denom = totals["cache_read_input_tokens"] + totals["cache_creation_input_tokens"] + totals["input_tokens"]
        expected = round(totals["cache_read_input_tokens"] / denom, 4)
        self.assertEqual(mined["cache_read_ratio"], expected)
        self.assertGreater(mined["cache_read_ratio"], 0.0)


class UserCorrectionTests(unittest.TestCase):
    def test_correction_detected_within_two_turns(self):
        mined = tm.mine(_fixture("user-correction.jsonl"))
        self.assertEqual(len(mined["friction_events"]), 1)
        self.assertEqual(len(mined["user_corrections"]), 1)
        corr = mined["user_corrections"][0]
        self.assertEqual(corr["turns_after_failure"], 2)
        self.assertEqual(corr["friction_line"], mined["friction_events"][0]["line"])
        self.assertIn("wrong", corr["excerpt"].lower())

    def test_no_correction_without_negation_phrase(self):
        # clean.jsonl has user turns but none contain a negation phrase,
        # and no friction event exists to correct against.
        mined = tm.mine(_fixture("clean.jsonl"))
        self.assertEqual(mined["user_corrections"], [])


class RedactionTests(unittest.TestCase):
    def setUp(self):
        self.mined = tm.mine(_fixture("friction.jsonl"))
        self.excerpt = next(
            e["excerpt"] for e in self.mined["friction_events"] if e["kind"] == "tool_error"
        )

    def test_secret_token_redacted(self):
        self.assertNotIn("ghp_FAKE", self.excerpt)
        self.assertIn("[REDACTED:", self.excerpt)

    def test_pii_email_redacted(self):
        self.assertNotIn("ops-support@fixture-example.test", self.excerpt)
        self.assertIn("[REDACTED:email]", self.excerpt)

    def test_pii_phone_redacted(self):
        self.assertNotIn("555-201-4488", self.excerpt)
        self.assertIn("[REDACTED:phone]", self.excerpt)

    def test_pii_address_redacted(self):
        self.assertNotIn("42 Fixture Lane", self.excerpt)
        self.assertIn("[REDACTED:address]", self.excerpt)

    def test_redact_pii_leaves_clean_text_untouched(self):
        clean = "Run the test suite and report the pass count."
        self.assertEqual(tm.redact_pii(clean), clean)

    def test_excerpt_truncated_to_max_chars(self):
        long_text = "x" * 5000
        excerpt = tm.make_excerpt(long_text)
        self.assertLessEqual(len(excerpt), tm.EXCERPT_MAX_CHARS)
        self.assertTrue(excerpt.endswith("..."))

    def test_redaction_happens_before_truncation(self):
        # A secret placed right at the truncation boundary must still be
        # fully redacted, not half-truncated into a leaked fragment.
        secret = "ghp_" + "A" * 40
        text = ("z" * 390) + secret
        excerpt = tm.make_excerpt(text)
        self.assertNotIn("ghp_", excerpt)
        self.assertNotIn("A" * 20, excerpt)


class RedactionPerformanceTests(unittest.TestCase):
    def test_large_at_free_digit_free_text_stays_fast(self):
        # Regression guard for the O(n^2) _EMAIL_RE backtracking blowup
        # on large text with no "@" (measured ~8s @ 100K chars before
        # redact_pii's short-circuits were added; this input is 2x that
        # and, quadratically, would have taken tens of seconds pre-fix).
        # Bound kept generous (2s) to avoid CI flake -- post-fix this
        # completes in low milliseconds.
        block = "abcdefghijklmnopqrstuvwxyz "  # no digits, no "@"
        text = (block * (200_000 // len(block) + 1))[:200_000]
        self.assertNotIn("@", text)
        self.assertFalse(any(ch.isdigit() for ch in text))

        start = time.monotonic()
        tm.make_excerpt(text)
        elapsed = time.monotonic() - start

        self.assertLess(
            elapsed, 2.0, f"make_excerpt() took {elapsed:.2f}s on 200K @-free/digit-free chars"
        )


class CommandPrefixRedactionTests(unittest.TestCase):
    """Regression guard: command_prefix and tool_name must be redacted the
    same way every other transcript-derived string is, all the way
    through to the assembled evidence bundle (Stage-2 review finding)."""

    def test_command_prefix_secrets_and_pii_masked_in_bundle(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "command-secret.jsonl"
            command = (
                "token=ghp_FAKEFAKEFAKEFAKEFAKEFAKEFAKEFAKE "
                "email=probe-user@fixture-example.test"
            )
            lines = [
                json.dumps(
                    {
                        "type": "user",
                        "sessionId": "cmd-secret-0001",
                        "cwd": "/Users/fixtureuser/code/command-secret",
                        "gitBranch": "main",
                        "version": "2.1.198",
                        "timestamp": "2026-01-01T10:00:00.000Z",
                        "message": {"role": "user", "content": [{"type": "text", "text": "run the probe"}]},
                    }
                ),
                json.dumps(
                    {
                        "type": "assistant",
                        "sessionId": "cmd-secret-0001",
                        "cwd": "/Users/fixtureuser/code/command-secret",
                        "gitBranch": "main",
                        "version": "2.1.198",
                        "timestamp": "2026-01-01T10:00:01.000Z",
                        "message": {
                            "role": "assistant",
                            "content": [
                                {"type": "tool_use", "id": "tool_1", "name": "Bash", "input": {"command": command}}
                            ],
                            "usage": {},
                        },
                    }
                ),
                json.dumps(
                    {
                        "type": "user",
                        "sessionId": "cmd-secret-0001",
                        "cwd": "/Users/fixtureuser/code/command-secret",
                        "gitBranch": "main",
                        "version": "2.1.198",
                        "timestamp": "2026-01-01T10:00:02.000Z",
                        "toolUseResult": {"exit_code": 1},
                        "message": {
                            "role": "user",
                            "content": [
                                {"type": "tool_result", "tool_use_id": "tool_1", "is_error": True, "content": "probe failed"}
                            ],
                        },
                    }
                ),
            ]
            path.write_text("\n".join(lines) + "\n", encoding="utf-8")

            bundle = tm.mine_to_evidence_bundle([path])
            self.assertEqual(bundle["friction_cluster_count"], 1)
            command_prefix = bundle["clusters"][0]["command_prefix"]
            self.assertNotIn("ghp_FAKE", command_prefix)
            self.assertNotIn("probe-user@fixture-example.test", command_prefix)
            self.assertIn("[REDACTED:", command_prefix)
            self.assertIn("[REDACTED:email]", command_prefix)

    def test_tool_name_redacted_defensively(self):
        # tool_name is drawn from a small fixed vocabulary in real
        # transcripts but is never validated against an enum -- confirm
        # it goes through the same redaction chain as command_prefix.
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "tool-name-secret.jsonl"
            lines = [
                json.dumps(
                    {
                        "type": "user",
                        "sessionId": "tool-name-0001",
                        "cwd": "/x",
                        "timestamp": "2026-01-01T10:00:00.000Z",
                        "message": {"role": "user", "content": [{"type": "text", "text": "go"}]},
                    }
                ),
                json.dumps(
                    {
                        "type": "assistant",
                        "sessionId": "tool-name-0001",
                        "cwd": "/x",
                        "timestamp": "2026-01-01T10:00:01.000Z",
                        "message": {
                            "role": "assistant",
                            "content": [
                                {
                                    "type": "tool_use",
                                    "id": "tool_1",
                                    "name": "ghp_FAKEFAKEFAKEFAKEFAKEFAKEFAKEFAKE",
                                    "input": {},
                                }
                            ],
                            "usage": {},
                        },
                    }
                ),
                json.dumps(
                    {
                        "type": "user",
                        "sessionId": "tool-name-0001",
                        "cwd": "/x",
                        "timestamp": "2026-01-01T10:00:02.000Z",
                        "message": {
                            "role": "user",
                            "content": [
                                {"type": "tool_result", "tool_use_id": "tool_1", "is_error": True, "content": "failed"}
                            ],
                        },
                    }
                ),
            ]
            path.write_text("\n".join(lines) + "\n", encoding="utf-8")

            mined = tm.mine(path)
            self.assertEqual(len(mined["friction_events"]), 1)
            tool_name = mined["friction_events"][0]["tool_name"]
            self.assertNotIn("ghp_FAKE", tool_name)
            self.assertIn("[REDACTED:", tool_name)


class ClusterAndBudgetTests(unittest.TestCase):
    def _synthetic_events(self, n_clusters=3, per_cluster=5):
        events = []
        for c in range(n_clusters):
            for i in range(per_cluster):
                events.append(
                    {
                        "kind": "tool_error",
                        "tool_name": "Bash",
                        "command_prefix": f"synthetic-cmd-{c}",
                        "excerpt": f"synthetic excerpt {c}-{i} " + ("pad" * 30),
                        "timestamp": f"2026-01-01T00:00:{i:02d}.000Z",
                        "session_id": f"session-{c}",
                        "line": i + 1,
                        "turn_index": i,
                    }
                )
        return events

    def test_cluster_groups_by_kind_tool_command(self):
        events = self._synthetic_events(n_clusters=3, per_cluster=4)
        clusters = tm.cluster(events)
        self.assertEqual(len(clusters), 3)
        for c in clusters:
            self.assertEqual(c["count"], 4)
            self.assertTrue(c["is_friction"])
            self.assertLessEqual(len(c["exemplars"]), tm.MAX_EXEMPLARS_PER_CLUSTER)

    def test_cluster_friction_fixture_distinct_signatures(self):
        mined_friction = tm.mine(_fixture("friction.jsonl"))
        mined_correction = tm.mine(_fixture("user-correction.jsonl"))
        events = mined_friction["friction_events"] + mined_correction["friction_events"]
        clusters = tm.cluster(events)
        # tool_error (deploy.sh), tool_error (sed), hook_error, prevented_continuation
        self.assertEqual(len(clusters), 4)

    def test_budget_keeps_floor_exemplar_and_respects_cap(self):
        events = self._synthetic_events(n_clusters=3, per_cluster=5)
        clusters = tm.cluster(events)

        full = tm.budget(clusters, max_input_tokens=10_000_000)
        floor = tm.budget(clusters, max_input_tokens=1)

        # Every friction cluster survives, none dropped, all down to the floor.
        self.assertEqual(len(floor["clusters"]), len(clusters))
        for c in floor["clusters"]:
            self.assertGreaterEqual(len(c["exemplars"]), 1)
            self.assertEqual(len(c["exemplars"]), 1)
        self.assertLess(floor["token_estimate"], full["token_estimate"])
        self.assertTrue(floor["over_budget"])  # target of 1 token is unreachable

        at_floor_budget = tm.budget(clusters, max_input_tokens=floor["token_estimate"])
        self.assertEqual(at_floor_budget["token_estimate"], floor["token_estimate"])
        self.assertFalse(at_floor_budget["over_budget"])
        for c in at_floor_budget["clusters"]:
            self.assertEqual(len(c["exemplars"]), 1)

    def test_normalize_command_prefix(self):
        raw = "  git   diff   --stat  \n\n  HEAD~1  "
        self.assertEqual(tm.normalize_command_prefix(raw), "git diff --stat HEAD~1")
        self.assertLessEqual(len(tm.normalize_command_prefix("x" * 500, max_len=80)), 80)


class SchemaCanaryTests(unittest.TestCase):
    def test_raises_on_drift_fixture(self):
        mined = tm.mine(_fixture("drift.jsonl"))
        self.assertEqual(mined["tool_use_count"], 1)
        self.assertEqual(mined["friction_field_presence"], 0)
        with self.assertRaises(tm.SchemaDriftError):
            tm.schema_canary([mined])

    def test_passes_on_friction_fixture(self):
        mined = tm.mine(_fixture("friction.jsonl"))
        result = tm.schema_canary([mined])
        self.assertIn("2.1.198", result["observed_versions"])
        self.assertEqual(result["untested_versions"], [])

    def test_passes_on_quiet_week_fixture_alone(self):
        # The critical adrev-015 regression guard: zero friction events
        # must NOT be conflated with drift when the fields were present
        # and simply reported no problems.
        mined = tm.mine(_fixture("quiet-week.jsonl"))
        self.assertEqual(mined["friction_events"], [])
        result = tm.schema_canary([mined])
        self.assertIn("2.1.198", result["observed_versions"])

    def test_untested_version_reported_not_raised(self):
        mined = tm.mine(_fixture("drift.jsonl"))
        mined["friction_field_presence"] = 1  # simulate a recognized-but-untested version
        result = tm.schema_canary([mined])
        self.assertIn("9.9.999", result["untested_versions"])

    def test_no_tool_use_no_friction_does_not_raise(self):
        # A session with zero tool_use blocks at all (pure conversation)
        # gives the canary nothing to judge -- must not raise.
        result = tm.schema_canary(
            [{"tool_use_count": 0, "friction_field_presence": 0, "transcript_version": "2.1.198"}]
        )
        self.assertEqual(result["observed_versions"], {"2.1.198": 1})


class MalformedLineTests(unittest.TestCase):
    def test_malformed_lines_skipped_and_counted(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "malformed.jsonl"
            lines = [
                json.dumps({"type": "user", "sessionId": "s1", "cwd": "/x", "timestamp": "2026-01-01T00:00:00.000Z", "message": {"role": "user", "content": [{"type": "text", "text": "hi"}]}}),
                "{not valid json,,,",
                json.dumps([1, 2, 3]),  # valid JSON, not a dict
                "",  # blank line, not counted as malformed
                json.dumps({"type": "assistant", "sessionId": "s1", "cwd": "/x", "timestamp": "2026-01-01T00:00:01.000Z", "message": {"role": "assistant", "content": [{"type": "text", "text": "hello"}], "usage": {}}}),
            ]
            path.write_text("\n".join(lines) + "\n", encoding="utf-8")

            mined = tm.mine(path)
            self.assertEqual(mined["malformed_line_count"], 2)
            self.assertEqual(mined["session_id"], "s1")


class WatermarkTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.mkdtemp(prefix="ccgm-dreaming-test-")
        self._prev = os.environ.get("CCGM_DREAMING_DIR")
        os.environ["CCGM_DREAMING_DIR"] = self._tmp

    def tearDown(self):
        if self._prev is None:
            os.environ.pop("CCGM_DREAMING_DIR", None)
        else:
            os.environ["CCGM_DREAMING_DIR"] = self._prev

    def test_round_trip_and_forward_only(self):
        self.assertEqual(tm.read_watermark(), {})
        tm.write_watermark("slug-a", "2026-01-01T00:00:00.000Z")
        self.assertEqual(tm.read_watermark(), {"slug-a": "2026-01-01T00:00:00.000Z"})

        # A second slug does not clobber the first.
        tm.write_watermark("slug-b", "2026-01-02T00:00:00.000Z")
        self.assertEqual(
            tm.read_watermark(),
            {"slug-a": "2026-01-01T00:00:00.000Z", "slug-b": "2026-01-02T00:00:00.000Z"},
        )

        # Advancing slug-a forward works.
        tm.write_watermark("slug-a", "2026-01-05T00:00:00.000Z")
        self.assertEqual(tm.read_watermark()["slug-a"], "2026-01-05T00:00:00.000Z")

        # An older timestamp is a no-op (never regress).
        tm.write_watermark("slug-a", "2026-01-03T00:00:00.000Z")
        self.assertEqual(tm.read_watermark()["slug-a"], "2026-01-05T00:00:00.000Z")

    def test_fractional_precision_timestamp_advances_over_non_fractional(self):
        # Regression guard: raw string comparison would refuse this
        # advance ("2026-01-01T10:00:00.500Z" > "2026-01-01T10:00:00Z" is
        # False in Python) even though the fractional value is 500ms
        # later in real time.
        tm.write_watermark("slug-precision", "2026-01-01T10:00:00Z")
        tm.write_watermark("slug-precision", "2026-01-01T10:00:00.500Z")
        self.assertEqual(tm.read_watermark()["slug-precision"], "2026-01-01T10:00:00.500Z")

    def test_older_non_fractional_does_not_regress_newer_fractional(self):
        # The other direction of the same string-vs-epoch comparison:
        # confirms the fix is epoch-correct both ways, not just flipped.
        tm.write_watermark("slug-precision-2", "2026-01-01T10:00:00.500Z")
        tm.write_watermark("slug-precision-2", "2026-01-01T10:00:00Z")
        self.assertEqual(tm.read_watermark()["slug-precision-2"], "2026-01-01T10:00:00.500Z")

    def test_concurrent_writers_on_distinct_slugs_all_land(self):
        # Regression guard for the unlocked read-modify-write race:
        # without the fcntl lock, a writer that reads the file before
        # another writer's update lands can clobber that update when it
        # writes last, silently dropping a DIFFERENT slug's watermark.
        # Threads genuinely race at the OS I/O level here -- fcntl.flock()
        # and file I/O release the GIL during the blocking syscall -- so
        # a Barrier-released burst of writers is a real concurrency test,
        # not just an interleaving simulation.
        n_workers = 16
        barrier = threading.Barrier(n_workers)
        errors: list[BaseException] = []

        def worker(i: int) -> None:
            try:
                barrier.wait(timeout=5)
                tm.write_watermark(f"slug-{i}", f"2026-01-01T00:00:{i:02d}.000Z")
            except BaseException as exc:  # noqa: BLE001 -- surfaced via `errors`, not swallowed
                errors.append(exc)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(n_workers)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        self.assertEqual(errors, [])
        result = tm.read_watermark()
        self.assertEqual(len(result), n_workers)
        for i in range(n_workers):
            self.assertEqual(result[f"slug-{i}"], f"2026-01-01T00:00:{i:02d}.000Z")


class DiscoverTests(unittest.TestCase):
    def _write_transcript(self, root: Path, project_dir: str, filename: str, cwd: str, ts_epoch: float | None = None):
        d = root / project_dir
        d.mkdir(parents=True, exist_ok=True)
        p = d / filename
        p.write_text(
            json.dumps(
                {
                    "type": "user",
                    "sessionId": filename,
                    "cwd": cwd,
                    "timestamp": "2026-01-01T00:00:00.000Z",
                    "message": {"role": "user", "content": [{"type": "text", "text": "hi"}]},
                }
            )
            + "\n",
            encoding="utf-8",
        )
        if ts_epoch is not None:
            os.utime(p, (ts_epoch, ts_epoch))
        return p

    def test_filters_by_resolved_slug_and_respects_watermark(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            wanted_cwd = "/Users/fixtureuser/code/discover-target"
            other_cwd = "/Users/fixtureuser/code/discover-other"
            wanted_slug = detect_project_slug(wanted_cwd)
            other_slug = detect_project_slug(other_cwd)
            self.assertNotEqual(wanted_slug, other_slug)

            p_wanted = self._write_transcript(root, "proj-a", "s1.jsonl", wanted_cwd)
            self._write_transcript(root, "proj-b", "s2.jsonl", other_cwd)

            found = tm.discover([wanted_slug], projects_root=root, lookback_days=365)
            self.assertEqual(found, [str(p_wanted)])

    def test_watermark_excludes_unchanged_file(self):
        import datetime as _dt

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            cwd = "/Users/fixtureuser/code/discover-watermark"
            slug = detect_project_slug(cwd)
            old_epoch = _dt.datetime(2026, 1, 1, tzinfo=_dt.timezone.utc).timestamp()
            self._write_transcript(root, "proj-c", "s3.jsonl", cwd, ts_epoch=old_epoch)

            watermark = {slug: "2026-06-01T00:00:00.000Z"}
            found = tm.discover([slug], since_watermark=watermark, projects_root=root, lookback_days=365)
            self.assertEqual(found, [])


class SchemaValidationTests(unittest.TestCase):
    def test_self_check_bundle_validates_against_schema(self):
        summary = tm.self_check()
        self.assertTrue(summary["ok"])
        self.assertTrue(summary["schema_valid"])
        self.assertTrue(summary["drift_fixture_raises_canary"])
        self.assertEqual(summary["fixtures_mined"], 4)

    def test_mine_to_evidence_bundle_validates_directly(self):
        paths = [_fixture(n) for n in ("friction.jsonl", "clean.jsonl", "user-correction.jsonl", "quiet-week.jsonl")]
        bundle = tm.mine_to_evidence_bundle(paths)
        schema_path = HERE.parent / "lib" / "evidence-bundle-schema.json"
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        errors = tm.validate_against_schema(bundle, schema)
        self.assertEqual(errors, [], msg="\n".join(errors))

    def test_validator_catches_missing_required_field(self):
        schema = {"type": "object", "required": ["a"], "properties": {"a": {"type": "string"}}}
        errors = tm.validate_against_schema({}, schema)
        self.assertEqual(len(errors), 1)
        self.assertIn("a", errors[0])

    def test_validator_catches_type_mismatch(self):
        schema = {"type": "integer"}
        errors = tm.validate_against_schema("not an int", schema)
        self.assertEqual(len(errors), 1)


class SlugAgreementTests(unittest.TestCase):
    """arch-1 regression guard: the miner's resolved slug for a fixture
    repo must equal learnings_store.detect_project_slug() for that SAME
    repo -- not merely agree with itself. Uses a real throwaway git repo
    (not a fixture file) so the git-remote-based resolution path is
    genuinely exercised, matching the plan's explicit warning that a
    basename-fallback-only test would trivially "pass" without proving
    arch-1's fix is wired correctly.
    """

    def test_miner_slug_matches_detect_project_slug_for_real_repo(self):
        with tempfile.TemporaryDirectory() as td:
            repo_dir = Path(td) / "arch1-fixture-repo"
            repo_dir.mkdir()
            subprocess.run(["git", "init", "-q"], cwd=repo_dir, check=True)
            subprocess.run(
                ["git", "remote", "add", "origin", "https://example.test/fixtureorg/arch1-fixture-repo.git"],
                cwd=repo_dir,
                check=True,
            )

            expected_slug = detect_project_slug(str(repo_dir))

            transcript = repo_dir / "session.jsonl"
            transcript.write_text(
                json.dumps(
                    {
                        "type": "user",
                        "sessionId": "arch1-check",
                        "cwd": str(repo_dir),
                        "timestamp": "2026-01-01T00:00:00.000Z",
                        "message": {"role": "user", "content": [{"type": "text", "text": "hi"}]},
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            mined = tm.mine(transcript)
            self.assertEqual(mined["slug"], expected_slug)
            # And it must NOT equal a bare basename/repo_detect-style slug
            # unless that happens to coincide -- assert the real git-remote
            # signal was actually used, not silently ignored.
            self.assertEqual(expected_slug, "fixtureorg-arch1-fixture-repo")


if __name__ == "__main__":
    unittest.main()
