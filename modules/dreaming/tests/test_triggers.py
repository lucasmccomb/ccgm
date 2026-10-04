#!/usr/bin/env python3
"""
Tests for modules/dreaming/lib/triggers.py (#1098 Phase 3.4): the
deterministic trigger matcher every add/supersede proposal carries.

Run with: python3 -m pytest modules/dreaming/tests/test_triggers.py -q
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "lib"))

import triggers  # noqa: E402


def T(kind, value):
    return {"kind": kind, "value": value}


class ValidateTriggerTests(unittest.TestCase):
    def test_accepts_each_kind(self):
        for trig in (
            T("regex", r"syntax error at or near \"\w+\""),
            T("command_prefix", "git branch -D"),
            T("path_glob", "migrations/*.sql"),
            T("phrase_set", ["blocked outside business hours", "permission denied"]),
        ):
            with self.subTest(trigger=trig):
                self.assertIsNone(triggers.validate_trigger(trig))

    def test_rejects_non_objects_and_unknown_kinds(self):
        for bad in (None, "regex", 3, [], {}, T("telepathy", "x"), {"kind": "regex"}, {"value": "abc"}):
            with self.subTest(bad=bad):
                self.assertIsNotNone(triggers.validate_trigger(bad))

    def test_rejects_wrong_value_types(self):
        self.assertIsNotNone(triggers.validate_trigger(T("regex", ["a"])))
        self.assertIsNotNone(triggers.validate_trigger(T("phrase_set", "just a string")))
        self.assertIsNotNone(triggers.validate_trigger(T("phrase_set", [])))
        self.assertIsNotNone(triggers.validate_trigger(T("phrase_set", ["ok phrase", 3])))

    def test_rejects_triggers_that_match_everything(self):
        for bad in (T("regex", ".*"), T("regex", "a?"), T("regex", "(?:)"), T("regex", "x"),
                    T("command_prefix", "g"), T("path_glob", "*"), T("path_glob", "**/*"),
                    T("phrase_set", ["ab"]), T("phrase_set", ["   "])):
            with self.subTest(bad=bad):
                self.assertIsNotNone(triggers.validate_trigger(bad))

    def test_rejects_bad_or_dangerous_regex(self):
        self.assertIsNotNone(triggers.validate_trigger(T("regex", "(unclosed")))
        self.assertIsNotNone(triggers.validate_trigger(T("regex", r"(a+)+$")))
        self.assertIsNotNone(triggers.validate_trigger(T("regex", "a" * 500)))


class MatchesTests(unittest.TestCase):
    def test_regex_is_case_insensitive_search(self):
        trig = T("regex", r"syntax error at or near \"order\"")
        self.assertTrue(triggers.matches(trig, 'ERROR: Syntax Error at or near "order" LINE 3'))
        self.assertFalse(triggers.matches(trig, "all good"))

    def test_phrase_set_matches_any_phrase_case_insensitively(self):
        trig = T("phrase_set", ["blocked outside business hours", "permission denied"])
        self.assertTrue(triggers.matches(trig, "deploy.sh: Permission Denied"))
        self.assertFalse(triggers.matches(trig, "deploy ok"))

    def test_command_prefix_matches_at_word_boundary_with_normalised_whitespace(self):
        trig = T("command_prefix", "git branch -D")
        self.assertTrue(triggers.matches(trig, "git branch -D feature/x"))
        self.assertTrue(triggers.matches(trig, "ran:  git   branch   -D old"))
        self.assertTrue(triggers.matches(trig, "cd repo && git branch -D old"))
        self.assertFalse(triggers.matches(trig, "digit branch -D x"))
        self.assertFalse(triggers.matches(trig, "git branch -d merged"))

    def test_path_glob_matches_paths_in_text_by_full_path_or_basename(self):
        trig = T("path_glob", "migrations/*.sql")
        self.assertTrue(triggers.matches(trig, "edited migrations/001_init.sql today"))
        self.assertFalse(triggers.matches(trig, "edited src/init.py"))
        self.assertTrue(triggers.matches(T("path_glob", "*.sql"), 'wrote "db/001_init.sql".'))
        self.assertFalse(triggers.matches(T("path_glob", "*.sql"), "no paths here"))

    def test_invalid_trigger_never_matches(self):
        self.assertFalse(triggers.matches(T("regex", "(unclosed"), "(unclosed"))
        self.assertFalse(triggers.matches(None, "anything"))
        self.assertFalse(triggers.matches(T("regex", ".*"), "anything"))

    def test_non_string_text_never_matches(self):
        self.assertFalse(triggers.matches(T("phrase_set", ["abc def"]), None))

    def test_matches_any(self):
        trig = T("phrase_set", ["needle here"])
        self.assertTrue(triggers.matches_any(trig, ["hay", "a needle here ok"]))
        self.assertFalse(triggers.matches_any(trig, ["hay", ""]))
        self.assertFalse(triggers.matches_any(trig, []))

    def test_huge_text_is_bounded(self):
        trig = T("phrase_set", ["needle here"])
        self.assertFalse(triggers.matches(trig, "x" * (triggers.MAX_TEXT_CHARS + 10) + "needle here"))


if __name__ == "__main__":
    unittest.main()
