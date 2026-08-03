#!/usr/bin/env python3
"""Proves the version floor actually gates the write path (Epic 1, issue
#954).

The security review's finding (plan.md Epic 1): a version floor that is
unit-tested in isolation (test_version_floor.py) but never proven to
gate the real write path is not a floor at all -- a caller could still
call `render_frontmatter()` on an unsupported version and silently write
broken frontmatter. This file asserts that with
`claude_code_supports_paths()` forced to False, `render_frontmatter()`:

  - writes NOTHING (the target file is left byte-identical, or is never
    created at all if it did not already exist)
  - returns (False, <a non-empty skip reason string>)

And, for symmetry, that when the gate passes, `render_frontmatter()`
actually writes a block-sequence `paths:` block (never flow-style,
per plan.md §8.3's "Emitted YAML" requirement).
"""
import os
import sys
import tempfile
import unittest
from unittest import mock

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.abspath(os.path.join(_HERE, "..", "..", "..", "lib"))
sys.path.insert(0, _REPO_ROOT)

import rule_tiering  # noqa: E402


class WritesNothingWhenUnsupportedTests(unittest.TestCase):
    def test_existing_file_is_left_byte_identical(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = os.path.join(tmp, "some-rule.md")
            original = "Some rule body.\nSecond line.\n"
            with open(target, "w", encoding="utf-8") as fh:
                fh.write(original)

            with mock.patch.object(rule_tiering, "claude_code_supports_paths", return_value=False):
                wrote, reason = rule_tiering.render_frontmatter(target, ["**/*.xyzzy"])

            self.assertFalse(wrote)
            self.assertIsInstance(reason, str)
            self.assertTrue(reason)  # non-empty skip reason
            with open(target, "r", encoding="utf-8") as fh:
                self.assertEqual(fh.read(), original)

    def test_nonexistent_target_is_not_created(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = os.path.join(tmp, "does-not-exist.md")

            with mock.patch.object(rule_tiering, "claude_code_supports_paths", return_value=False):
                wrote, reason = rule_tiering.render_frontmatter(target, ["**/*.xyzzy"])

            self.assertFalse(wrote)
            self.assertIsInstance(reason, str)
            self.assertTrue(reason)
            self.assertFalse(os.path.exists(target))

    def test_gate_is_consulted_with_the_same_version_string_argument(self):
        # render_frontmatter must delegate the version check to
        # claude_code_supports_paths() rather than re-implementing its
        # own parsing -- a single source of truth for the floor.
        with tempfile.TemporaryDirectory() as tmp:
            target = os.path.join(tmp, "some-rule.md")
            with mock.patch.object(
                rule_tiering, "claude_code_supports_paths", return_value=False
            ) as gate:
                rule_tiering.render_frontmatter(target, ["**/*.xyzzy"], version_string="2.1.206")
            gate.assert_called_once_with("2.1.206")

    def test_empty_paths_list_also_refuses_to_write(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = os.path.join(tmp, "some-rule.md")
            with mock.patch.object(rule_tiering, "claude_code_supports_paths", return_value=True):
                wrote, reason = rule_tiering.render_frontmatter(target, [])
            self.assertFalse(wrote)
            self.assertIsInstance(reason, str)
            self.assertTrue(reason)
            self.assertFalse(os.path.exists(target))


class WritesWhenSupportedTests(unittest.TestCase):
    """Symmetry coverage: the gate passing actually writes something."""

    def test_writes_block_sequence_frontmatter_never_flow_style(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = os.path.join(tmp, "some-rule.md")
            with open(target, "w", encoding="utf-8") as fh:
                fh.write("Original body.\n")

            with mock.patch.object(rule_tiering, "claude_code_supports_paths", return_value=True):
                wrote, reason = rule_tiering.render_frontmatter(
                    target, ["**/*.tsx", "**/*.css"]
                )

            self.assertTrue(wrote)
            self.assertIsInstance(reason, str)
            self.assertTrue(reason)
            with open(target, "r", encoding="utf-8") as fh:
                content = fh.read()
            self.assertTrue(content.startswith("---\npaths:\n"))
            self.assertIn('  - "**/*.tsx"', content)
            self.assertIn('  - "**/*.css"', content)
            self.assertTrue(content.endswith("Original body.\n"))
            # Never flow-style: no line may open a value with '[' or '{'
            # (plan.md §8.3's frontmatter-YAML guard rejects that shape).
            for line in content.splitlines():
                stripped = line.split(":", 1)[-1].strip()
                self.assertFalse(stripped.startswith("["))
                self.assertFalse(stripped.startswith("{"))

    def test_writes_to_a_target_that_does_not_yet_exist(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = os.path.join(tmp, "new-rule.md")
            with mock.patch.object(rule_tiering, "claude_code_supports_paths", return_value=True):
                wrote, _reason = rule_tiering.render_frontmatter(target, ["**/*.xyzzy"])
            self.assertTrue(wrote)
            self.assertTrue(os.path.isfile(target))


if __name__ == "__main__":
    unittest.main()
