#!/usr/bin/env python3
"""Unit tests for the InstructionsLoaded measurement harness (Epic 7, issue #953).

Covers:
  - parse_log(): empty file, a malformed line (skipped, not raised), a valid
    line, and a missing file (raises FileNotFoundError -- the signal
    assert_loaded() below translates into LogMissingError)
  - assert_loaded(): raises a DISTINCT, NAMED error for "log absent"
    (LogMissingError) versus "rule absent from a present log"
    (RuleNotLoadedError) -- a missing log must never read as a passing
    absence assertion
  - hooks/instructions-loaded-log.py: never raises on malformed stdin
    (always exits 0), and writes go through hook_utils.file_locked_append()
"""
import importlib.util
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

_HERE = os.path.dirname(os.path.abspath(__file__))
_MODULE_DIR = os.path.join(_HERE, "..")
_LIB_DIR = os.path.join(_MODULE_DIR, "lib")
_HOOK_UTILS_LIB = os.path.abspath(os.path.join(_MODULE_DIR, "..", "hooks", "lib"))
_HOOK_PATH = os.path.join(_MODULE_DIR, "hooks", "instructions-loaded-log.py")

# hook_utils.py lives in the sibling `hooks` module's lib/, not this
# module's own lib/. Insert it BEFORE importing anything so both the
# library under test and the hook module (imported below via
# importlib, since its filename is hyphenated) can resolve `import
# hook_utils` regardless of whether a real ~/.claude install exists on
# the machine running the tests.
sys.path.insert(0, _HOOK_UTILS_LIB)
sys.path.insert(0, _LIB_DIR)

import loaded_log  # noqa: E402


def _load_hook_module():
    """Import instructions-loaded-log.py as a module.

    Uses importlib because the filename is hyphenated and cannot be the
    target of a normal `import` statement.
    """
    spec = importlib.util.spec_from_file_location(
        "ccgm_test_instructions_loaded_log", _HOOK_PATH
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write_jsonl(path, lines):
    with open(path, "w", encoding="utf-8") as fh:
        for line in lines:
            fh.write(line + "\n")


class ParseLogTests(unittest.TestCase):
    def test_missing_file_raises_file_not_found(self):
        with tempfile.TemporaryDirectory() as tmp:
            missing = os.path.join(tmp, "does-not-exist.jsonl")
            with self.assertRaises(FileNotFoundError):
                loaded_log.parse_log(missing)

    def test_empty_file_returns_empty_list(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "empty.jsonl")
            _write_jsonl(path, [])
            self.assertEqual(loaded_log.parse_log(path), [])

    def test_malformed_line_is_skipped_not_raised(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "malformed.jsonl")
            _write_jsonl(
                path,
                [
                    "{not valid json",
                    '{"file_path": "/a/b/c.md"}',
                    "",  # blank line, also must not raise
                ],
            )
            records = loaded_log.parse_log(path)
            self.assertEqual(len(records), 1)
            self.assertEqual(records[0]["file_path"], "/a/b/c.md")

    def test_valid_json_that_is_not_an_object_is_skipped(self):
        """A bare list, string, number or null must be dropped, not returned.

        parse_log() promises a list of record dicts; a caller iterating the
        result and doing record["file_path"] would raise on a bare scalar.
        """
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "non-object.jsonl")
            _write_jsonl(
                path,
                [
                    "[1, 2, 3]",
                    '"a bare string"',
                    "42",
                    "null",
                    '{"file_path": "/a/b/c.md"}',
                ],
            )
            records = loaded_log.parse_log(path)
            self.assertEqual(len(records), 1)
            self.assertEqual(records[0]["file_path"], "/a/b/c.md")

    def test_invalid_utf8_line_does_not_discard_the_rest_of_the_log(self):
        """One corrupt byte must not discard the rest of the day's log.

        Deliberately asserts only that the surrounding records survive,
        not the corrupt line's own retain/drop disposition -- that is
        data-dependent (the replaced line may or may not still parse as
        JSON) and is not a property callers should rely on.

        The decode happens in the line iterator, outside the json.loads()
        guard, so without errors="replace" this raises UnicodeDecodeError
        and every record in the file is lost -- including the valid ones
        written before the corruption.
        """
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "bad-utf8.jsonl")
            with open(path, "wb") as fh:
                fh.write(b'{"file_path": "/a/b/before.md"}\n')
                fh.write(b'{"file_path": "\xff\xfe not utf8"}\n')
                fh.write(b'{"file_path": "/a/b/after.md"}\n')
            records = loaded_log.parse_log(path)
            paths = [r["file_path"] for r in records]
            self.assertIn("/a/b/before.md", paths)
            self.assertIn("/a/b/after.md", paths)

    def test_valid_line_is_parsed(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "valid.jsonl")
            record = {
                "hook_event_name": "InstructionsLoaded",
                "file_path": "/Users/x/code/ccgm/modules/tailwind/rules/tailwind.md",
                "memory_type": "User",
                "load_reason": "session_start",
            }
            _write_jsonl(path, [json.dumps(record)])
            records = loaded_log.parse_log(path)
            self.assertEqual(records, [record])


class AssertLoadedTests(unittest.TestCase):
    def test_missing_log_raises_log_missing_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            missing = os.path.join(tmp, "does-not-exist.jsonl")
            with self.assertRaises(loaded_log.LogMissingError):
                loaded_log.assert_loaded(missing, "rules/tailwind.md")

    def test_present_log_without_rule_raises_rule_not_loaded_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "log.jsonl")
            _write_jsonl(
                path,
                [json.dumps({"file_path": "/Users/x/code/ccgm/modules/supabase/rules/supabase.md"})],
            )
            with self.assertRaises(loaded_log.RuleNotLoadedError):
                loaded_log.assert_loaded(path, "rules/tailwind.md")

    def test_log_missing_error_and_rule_not_loaded_error_are_distinct(self):
        # The two failure modes must never be conflatable: a caller that
        # only catches one must not accidentally swallow the other.
        self.assertFalse(issubclass(loaded_log.LogMissingError, loaded_log.RuleNotLoadedError))
        self.assertFalse(issubclass(loaded_log.RuleNotLoadedError, loaded_log.LogMissingError))
        self.assertTrue(issubclass(loaded_log.LogMissingError, Exception))
        self.assertTrue(issubclass(loaded_log.RuleNotLoadedError, Exception))

    def test_present_log_with_exact_rule_path_passes_silently(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "log.jsonl")
            rule_path = "/Users/x/code/ccgm/modules/tailwind/rules/tailwind.md"
            _write_jsonl(path, [json.dumps({"file_path": rule_path})])
            # Must not raise.
            loaded_log.assert_loaded(path, rule_path)

    def test_present_log_matches_module_relative_suffix(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "log.jsonl")
            absolute = "/Users/x/code/ccgm/modules/tailwind/rules/tailwind.md"
            _write_jsonl(path, [json.dumps({"file_path": absolute})])
            # Caller passes a shorter, module-relative path -- still a match.
            loaded_log.assert_loaded(path, "rules/tailwind.md")

    def test_malformed_lines_do_not_prevent_matching_a_later_valid_line(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "log.jsonl")
            rule_path = "/Users/x/code/ccgm/modules/tailwind/rules/tailwind.md"
            _write_jsonl(path, ["not json at all", json.dumps({"file_path": rule_path})])
            loaded_log.assert_loaded(path, rule_path)


class BuildRecordTests(unittest.TestCase):
    """Pure-function tests on the hook's build_record(), imported in-process."""

    @classmethod
    def setUpClass(cls):
        cls.hook = _load_hook_module()

    def test_extracts_known_fields(self):
        payload = {
            "session_id": "abc-123",
            "transcript_path": "/Users/x/.claude/projects/p/abc-123.jsonl",
            "cwd": "/Users/x/scratch",
            "hook_event_name": "InstructionsLoaded",
            "file_path": "/Users/x/code/ccgm/modules/tailwind/rules/tailwind.md",
            "memory_type": "User",
            "load_reason": "session_start",
        }
        record = self.hook.build_record(payload)
        self.assertEqual(record["session_id"], "abc-123")
        self.assertEqual(record["cwd"], "/Users/x/scratch")
        self.assertEqual(record["file_path"], payload["file_path"])
        self.assertEqual(record["memory_type"], "User")
        self.assertEqual(record["load_reason"], "session_start")
        self.assertEqual(record["hook_event_name"], "InstructionsLoaded")
        self.assertIn("timestamp", record)
        self.assertEqual(record["raw"]["file_path"], payload["file_path"])

    def test_missing_fields_become_none_not_raised(self):
        record = self.hook.build_record({})
        self.assertIsNone(record["session_id"])
        self.assertIsNone(record["cwd"])
        self.assertIsNone(record["file_path"])
        self.assertIsNone(record["memory_type"])
        self.assertIsNone(record["load_reason"])
        # hook_event_name defaults rather than going None, since the log's
        # own purpose is naming which event produced the record.
        self.assertEqual(record["hook_event_name"], "InstructionsLoaded")

    def test_raw_payload_is_passed_through_redact_secrets(self):
        # Proves the raw payload goes through hook_utils.redact_secrets()
        # before being stored, without embedding a real-secret-shaped
        # fixture in the repo (which a secret scanner would flag even
        # though it is synthetic test data).
        payload = {"cwd": "some-marker-value"}
        with mock.patch.object(
            self.hook.hook_utils, "redact_secrets", wraps=self.hook.hook_utils.redact_secrets
        ) as spy:
            record = self.hook.build_record(payload)
        self.assertTrue(spy.called)
        self.assertEqual(record["raw"]["cwd"], "some-marker-value")


class HookProcessTests(unittest.TestCase):
    """Black-box (subprocess) and in-process behavior of the hook itself."""

    def _run_hook(self, stdin_text, rule_loading_dir):
        env = dict(os.environ)
        env["CCGM_RULE_LOADING_DIR"] = rule_loading_dir
        env["PYTHONPATH"] = _HOOK_UTILS_LIB + os.pathsep + env.get("PYTHONPATH", "")
        return subprocess.run(
            [sys.executable, _HOOK_PATH],
            input=stdin_text,
            capture_output=True,
            text=True,
            env=env,
        )

    def test_never_raises_on_malformed_stdin_exits_zero(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = self._run_hook("{not valid json at all", tmp)
            self.assertEqual(result.returncode, 0, msg=result.stderr)

    def test_exits_zero_on_minimal_valid_input(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = self._run_hook("{}", tmp)
            self.assertEqual(result.returncode, 0, msg=result.stderr)

    def test_exits_zero_on_empty_stdin(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = self._run_hook("", tmp)
            self.assertEqual(result.returncode, 0, msg=result.stderr)

    def test_appends_expected_record_to_target_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            payload = {
                "session_id": "sess-1",
                "cwd": "/Users/x/scratch",
                "hook_event_name": "InstructionsLoaded",
                "file_path": "/Users/x/code/ccgm/modules/tailwind/rules/tailwind.md",
                "memory_type": "User",
                "load_reason": "session_start",
            }
            result = self._run_hook(json.dumps(payload), tmp)
            self.assertEqual(result.returncode, 0, msg=result.stderr)

            files = os.listdir(tmp)
            self.assertEqual(len(files), 1)
            log_path = os.path.join(tmp, files[0])
            records = loaded_log.parse_log(log_path)
            self.assertEqual(len(records), 1)
            self.assertEqual(records[0]["file_path"], payload["file_path"])
            self.assertEqual(records[0]["session_id"], "sess-1")

    def test_writes_go_through_file_locked_append(self):
        """Proves the hook's write path is hook_utils.file_locked_append(),
        not a raw open()/write(), by patching it and asserting the call."""
        hook_module = _load_hook_module()
        calls = []

        def _recording_append(path, data):
            calls.append((path, data))

        stdin_payload = json.dumps({"file_path": "/x/y/z.md"})

        with mock.patch.object(
            hook_module.hook_utils, "file_locked_append", side_effect=_recording_append
        ):
            with mock.patch.object(sys, "stdin", io.StringIO(stdin_payload)):
                with tempfile.TemporaryDirectory() as tmp:
                    with mock.patch.dict(os.environ, {"CCGM_RULE_LOADING_DIR": tmp}):
                        with self.assertRaises(SystemExit) as ctx:
                            hook_module.main()
                        self.assertEqual(ctx.exception.code, 0)

        self.assertEqual(len(calls), 1)
        called_path, called_data = calls[0]
        self.assertTrue(called_path.startswith(tmp))
        self.assertIn("/x/y/z.md", called_data)


if __name__ == "__main__":
    unittest.main()
