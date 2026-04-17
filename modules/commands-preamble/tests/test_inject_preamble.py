#!/usr/bin/env python3
"""Unit tests for inject-preamble UserPromptSubmit hook."""
from __future__ import annotations

import importlib.util
import io
import json
import os
import sys
import tempfile
import unittest
from unittest.mock import patch


_TEST_DIR = os.path.dirname(os.path.abspath(__file__))
_HOOK_PATH = os.path.join(_TEST_DIR, "..", "hooks", "inject-preamble.py")

# Load the hook module under a stable name. It has a hyphen in its filename,
# which the normal `import` machinery rejects.
_spec = importlib.util.spec_from_file_location("inject_preamble", _HOOK_PATH)
inject_preamble = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(inject_preamble)


class TestIsSlashCommand(unittest.TestCase):
    def test_simple_slash_command(self):
        self.assertTrue(inject_preamble.is_slash_command("/review"))
        self.assertTrue(inject_preamble.is_slash_command("/cpm"))

    def test_slash_command_with_args(self):
        self.assertTrue(
            inject_preamble.is_slash_command("/commit some message here")
        )

    def test_leading_whitespace_is_tolerated(self):
        self.assertTrue(inject_preamble.is_slash_command("  /review"))

    def test_regular_prompt_is_not_a_command(self):
        self.assertFalse(inject_preamble.is_slash_command("fix the auth bug"))
        self.assertFalse(
            inject_preamble.is_slash_command("what does this do?")
        )

    def test_path_like_prompt_is_not_a_command(self):
        # Paths have multiple slashes in the first token.
        self.assertFalse(
            inject_preamble.is_slash_command("/home/user/code/foo.md")
        )
        self.assertFalse(inject_preamble.is_slash_command("/path/to/file"))

    def test_lone_slash_is_not_a_command(self):
        self.assertFalse(inject_preamble.is_slash_command("/"))
        self.assertFalse(inject_preamble.is_slash_command(""))


class TestIsEnabled(unittest.TestCase):
    def test_disabled_when_flag_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(inject_preamble, "ENABLE_FLAG",
                              os.path.join(tmp, "preamble.enabled")):
                self.assertFalse(inject_preamble.is_enabled())

    def test_enabled_when_flag_present(self):
        with tempfile.TemporaryDirectory() as tmp:
            flag = os.path.join(tmp, "preamble.enabled")
            open(flag, "w").close()
            with patch.object(inject_preamble, "ENABLE_FLAG", flag):
                self.assertTrue(inject_preamble.is_enabled())


class TestReadPreamble(unittest.TestCase):
    def test_returns_file_contents(self):
        with tempfile.TemporaryDirectory() as tmp:
            pf = os.path.join(tmp, "preamble.md")
            with open(pf, "w") as f:
                f.write("## Core Principles\n\nBe honest.\n")
            with patch.object(inject_preamble, "PREAMBLE_FILE", pf):
                self.assertEqual(
                    inject_preamble.read_preamble(),
                    "## Core Principles\n\nBe honest.",
                )

    def test_returns_empty_when_missing(self):
        with patch.object(inject_preamble, "PREAMBLE_FILE",
                          "/nonexistent/path/preamble.md"):
            self.assertEqual(inject_preamble.read_preamble(), "")


class TestBuildInjection(unittest.TestCase):
    def test_wraps_in_tagged_block(self):
        out = inject_preamble.build_injection("PRINCIPLES")
        self.assertIn("<command-preamble>", out)
        self.assertIn("</command-preamble>", out)
        self.assertIn("PRINCIPLES", out)
        self.assertIn("authoritative", out)


class TestMainIntegration(unittest.TestCase):
    """End-to-end: run main() with crafted stdin and check stdout."""

    def _run_main(self, prompt: str, enable_flag_exists: bool,
                  preamble_contents: str | None) -> str:
        with tempfile.TemporaryDirectory() as tmp:
            flag = os.path.join(tmp, "preamble.enabled")
            if enable_flag_exists:
                open(flag, "w").close()
            pf = os.path.join(tmp, "preamble.md")
            if preamble_contents is not None:
                with open(pf, "w") as f:
                    f.write(preamble_contents)

            stdin_payload = json.dumps({"prompt": prompt})
            stdout_buf = io.StringIO()

            with patch.object(inject_preamble, "ENABLE_FLAG", flag), \
                 patch.object(inject_preamble, "PREAMBLE_FILE", pf), \
                 patch.object(sys, "stdin", io.StringIO(stdin_payload)), \
                 patch.object(sys, "stdout", stdout_buf):
                try:
                    inject_preamble.main()
                except SystemExit:
                    pass
            return stdout_buf.getvalue()

    def test_injects_when_enabled_and_slash_command(self):
        out = self._run_main(
            prompt="/review",
            enable_flag_exists=True,
            preamble_contents="BE CAREFUL",
        )
        self.assertIn("<command-preamble>", out)
        self.assertIn("BE CAREFUL", out)

    def test_silent_when_disabled(self):
        out = self._run_main(
            prompt="/review",
            enable_flag_exists=False,
            preamble_contents="BE CAREFUL",
        )
        self.assertEqual(out, "")

    def test_silent_for_non_command_prompt(self):
        out = self._run_main(
            prompt="please fix the bug",
            enable_flag_exists=True,
            preamble_contents="BE CAREFUL",
        )
        self.assertEqual(out, "")

    def test_silent_when_preamble_file_missing(self):
        out = self._run_main(
            prompt="/review",
            enable_flag_exists=True,
            preamble_contents=None,
        )
        self.assertEqual(out, "")


if __name__ == "__main__":
    unittest.main()
