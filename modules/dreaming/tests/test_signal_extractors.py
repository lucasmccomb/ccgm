#!/usr/bin/env python3
"""
Tests for the four deterministic signal extractors in
modules/dreaming/lib/transcript_miner.py (#1098 Phase 3.1): human
redirections, resolved struggle arcs, rediscovery, abandoned work.

Every transcript here is synthetic (tests/transcript_fixtures.py); nothing is
captured from a real session.

Run with: python3 -m pytest modules/dreaming/tests/test_signal_extractors.py -q
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "lib"))
sys.path.insert(0, str(HERE))

import transcript_miner as tm  # noqa: E402
import transcript_fixtures as tf  # noqa: E402


def _mine(turns, **kwargs):
    tmp = Path(tempfile.mkdtemp(prefix="ccgm-signals-"))
    path = tf.write_transcript(tmp / "t.jsonl", turns, **kwargs)
    return tm.mine(path)


def _kinds(mined, kind):
    return [s for s in mined["signals"] if s["kind"] == kind]


def _after_work(text):
    """Mine a session where the human types `text` after the assistant has
    already answered once."""
    return _mine([tf.user_turn("Do the task."), tf.assistant_turn("Done, here is the result."), tf.user_turn(text)])


def _bash(tid, command):
    return {"id": tid, "name": "Bash", "input": {"command": command}}


def _fail_then_success_turns(command, failures, final_text, *, success_command=None):
    """`failures` failed runs of `command`, then one success, then assistant text."""
    turns = [tf.user_turn("Get the tests passing.")]
    for i in range(failures):
        tid = f"f{i}"
        turns.append(tf.assistant_turn("Trying again.", tool_uses=[_bash(tid, command)]))
        turns.append(tf.friction_turn(tool_use_id=tid, content="FAILED tests/test_x.py::test_a", exit_code=1))
    turns.append(tf.assistant_turn("", tool_uses=[_bash("ok", success_command or command)]))
    turns.append(tf.tool_result_turn(tool_use_id="ok", content="1 passed", exit_code=0))
    turns.append(tf.assistant_turn(final_text))
    return turns


class RedirectionTests(unittest.TestCase):
    def test_human_redirection_without_any_tool_error(self):
        turns = [
            tf.user_turn("Format the config."),
            tf.assistant_turn("I reformatted config.yaml with tabs."),
            tf.user_turn("No, we don't use tabs in this repo. Always use two spaces instead."),
        ]
        mined = _mine(turns)
        self.assertEqual(mined["friction_events"], [])
        found = _kinds(mined, "redirection")
        self.assertEqual(len(found), 1)
        self.assertIn("we don't use tabs", found[0]["excerpt"])
        self.assertIn("reformatted config.yaml", found[0]["context"])
        self.assertEqual(found[0]["session_id"], tf.DEFAULT_SESSION_ID)

    def test_redirection_context_skips_tool_only_assistant_turns(self):
        turns = [
            tf.user_turn("Fix it."),
            tf.assistant_turn("Switching the build to webpack."),
            tf.assistant_turn("", tool_uses=[_bash("t1", "ls")]),
            tf.tool_result_turn(tool_use_id="t1", content="a b c"),
            tf.user_turn("I want vite here, not webpack."),
        ]
        found = _kinds(_mine(turns), "redirection")
        self.assertEqual(len(found), 1)
        self.assertIn("Switching the build to webpack", found[0]["context"])

    def test_redirection_after_tool_only_assistant_turns_has_empty_context(self):
        turns = [
            tf.user_turn("Fix it."),
            tf.assistant_turn("", tool_uses=[_bash("t1", "ls")]),
            tf.tool_result_turn(tool_use_id="t1", content="a b c"),
            tf.user_turn("Never commit directly to main."),
        ]
        found = _kinds(_mine(turns), "redirection")
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["context"], "")

    def test_the_sessions_opening_prompt_is_a_task_not_a_redirection(self):
        # Nothing has happened yet, so there is nothing to redirect or undo.
        for text in ("I want a cheat sheet of interview questions.", "Never commit to main. Always use pnpm.", "Revert the last commit."):
            with self.subTest(text=text):
                mined = _mine([tf.user_turn(text)])
                self.assertEqual(mined["signals"], [])

    def test_a_mid_session_start_does_not_count_as_the_opening_prompt(self):
        tmp = Path(tempfile.mkdtemp(prefix="ccgm-cursor-"))
        path = tmp / "t.jsonl"
        head = tf.build_transcript([tf.user_turn("hello"), tf.assistant_turn("hi")])
        path.write_text(tf.to_jsonl(head), encoding="utf-8")
        offset = path.stat().st_size
        tail = tf.build_transcript([tf.user_turn("hello"), tf.assistant_turn("hi"), tf.user_turn("No, never do that.")])[2:]
        with path.open("a", encoding="utf-8") as fh:
            fh.write(tf.to_jsonl(tail))
        self.assertEqual(len(_kinds(tm.mine(path, offset), "redirection")), 1)

    def test_each_phrase_family_is_recognised(self):
        for text in (
            "that's wrong",
            "Always run the linter before pushing.",
            "never push to main",
            "Use pnpm instead of npm.",
            "I want a smaller diff.",
            "No, use the other file.",
            "We do not mock the database here.",
        ):
            with self.subTest(text=text):
                self.assertEqual(len(_kinds(_after_work(text), "redirection")), 1)

    def test_neutral_human_turn_is_not_a_redirection(self):
        self.assertEqual(_kinds(_after_work("Please add a test for the parser."), "redirection"), [])

    def test_word_boundaries(self):
        # "nobody", "know", "neverland" must not trip the no/never rules.
        for text in ("Nobody knows why this passes.", "Show me neverland.rb"):
            with self.subTest(text=text):
                self.assertEqual(_kinds(_after_work(text), "redirection"), [])

    def test_harness_reminder_is_not_a_redirection(self):
        turns = [
            tf.user_turn("<system-reminder>You must never skip the plan. Always use the tool.</system-reminder>", human=False),
            tf.user_turn("<system-reminder>Never do X, always do Y instead.</system-reminder>"),  # even if origin-marked
        ]
        self.assertEqual(_kinds(_mine(turns), "redirection"), [])

    def test_long_skill_expansion_is_not_a_redirection(self):
        body = "Base directory for this skill: /x\n" + ("Always follow these steps instead of guessing. " * 80)
        turns = [tf.user_turn(body, human=False), tf.user_turn(body)]  # unmarked and origin-marked
        self.assertEqual(_kinds(_mine(turns), "redirection"), [])

    def test_tool_result_negation_is_not_a_redirection(self):
        turns = [
            tf.user_turn("Run it."),
            tf.assistant_turn("", tool_uses=[_bash("t1", "make")]),
            tf.friction_turn(tool_use_id="t1", content="No, that's wrong: never use this target instead", exit_code=2),
        ]
        self.assertEqual(_kinds(_mine(turns), "redirection"), [])

    def test_meta_flagged_user_turn_is_not_a_redirection(self):
        turn = tf.user_turn("Always do this instead.")
        turn["isMeta"] = True
        self.assertEqual(_kinds(_mine([turn]), "redirection"), [])

    def test_excerpts_are_redacted(self):
        turns = [
            tf.assistant_turn("Emailing the report."),
            tf.user_turn("No, never email jane.doe@example.com directly."),
        ]
        found = _kinds(_mine(turns), "redirection")
        self.assertEqual(len(found), 1)
        self.assertNotIn("jane.doe@example.com", found[0]["excerpt"])
        self.assertIn("[REDACTED:email]", found[0]["excerpt"])

    def test_redirection_is_independent_of_friction_proximity(self):
        # Correction far (>2 turns) from any tool error still counts.
        turns = tf.correction_sequence(correction="No, that's wrong, use make instead.") + [tf.assistant_turn("ok")] * 4 + [tf.user_turn("No, that's wrong, use make.")]
        mined = _mine(turns)
        self.assertEqual(len(_kinds(mined, "redirection")), 2)


class StruggleArcTests(unittest.TestCase):
    def test_three_failures_then_success_yields_arc_with_conclusion(self):
        final = (
            "Ran the suite again. The root cause was a stale fixture path. "
            "I also tidied imports. The fix is to regenerate the snapshot."
        )
        mined = _mine(_fail_then_success_turns("pytest tests/test_x.py -q", 3, final))
        arcs = _kinds(mined, "struggle_arc")
        self.assertEqual(len(arcs), 1)
        self.assertEqual(arcs[0]["failure_count"], 3)
        self.assertIn("root cause was a stale fixture path", arcs[0]["excerpt"])
        self.assertIn("The fix is to regenerate the snapshot", arcs[0]["excerpt"])
        # Prefers the conclusion sentences over filler.
        self.assertLess(arcs[0]["excerpt"].index("root cause"), len(arcs[0]["excerpt"]))
        self.assertNotIn("tidied imports", arcs[0]["excerpt"])

    def test_two_failures_then_success_is_not_an_arc(self):
        mined = _mine(_fail_then_success_turns("pytest tests/test_x.py -q", 2, "The root cause was X."))
        self.assertEqual(_kinds(mined, "struggle_arc"), [])

    def test_failures_without_success_is_not_an_arc(self):
        turns = [tf.user_turn("go")]
        for i in range(4):
            turns.append(tf.assistant_turn("again", tool_uses=[_bash(f"f{i}", "make build")]))
            turns.append(tf.friction_turn(tool_use_id=f"f{i}", content="boom", exit_code=1))
        self.assertEqual(_kinds(_mine(turns), "struggle_arc"), [])

    def test_success_on_a_different_signature_does_not_close_the_arc(self):
        turns = _fail_then_success_turns("pytest tests/test_x.py -q", 3, "done", success_command="ls -la")
        self.assertEqual(_kinds(_mine(turns), "struggle_arc"), [])

    def test_success_in_the_middle_resets_the_count(self):
        turns = [tf.user_turn("go")]
        seq = ["f", "f", "ok", "f"]
        for i, kind in enumerate(seq):
            tid = f"t{i}"
            turns.append(tf.assistant_turn("", tool_uses=[_bash(tid, "make build")]))
            if kind == "f":
                turns.append(tf.friction_turn(tool_use_id=tid, content="boom", exit_code=1))
            else:
                turns.append(tf.tool_result_turn(tool_use_id=tid, content="built", exit_code=0))
        turns.append(tf.assistant_turn("", tool_uses=[_bash("last", "make build")]))
        turns.append(tf.tool_result_turn(tool_use_id="last", content="built", exit_code=0))
        turns.append(tf.assistant_turn("The fix was clean."))
        self.assertEqual(_kinds(_mine(turns), "struggle_arc"), [])

    def test_file_path_signature_covers_edit_attempts(self):
        turns = [tf.user_turn("fix the file")]
        for i in range(3):
            tid = f"e{i}"
            turns.append(tf.assistant_turn("", tool_uses=[{"id": tid, "name": "Edit", "input": {"file_path": "src/app.py", "old_string": f"v{i}"}}]))
            turns.append(tf.tool_result_turn(tool_use_id=tid, content="String to replace not found", is_error=True))
        turns.append(tf.assistant_turn("", tool_uses=[{"id": "ok", "name": "Edit", "input": {"file_path": "src/app.py", "old_string": "real"}}]))
        turns.append(tf.tool_result_turn(tool_use_id="ok", content="edited"))
        turns.append(tf.assistant_turn("Turns out the file uses tabs because of the formatter."))
        arcs = _kinds(_mine(turns), "struggle_arc")
        self.assertEqual(len(arcs), 1)
        self.assertIn("Turns out the file uses tabs", arcs[0]["excerpt"])
        self.assertIn("src/app.py", arcs[0]["signature"])

    def test_arc_without_following_assistant_text_is_skipped(self):
        turns = _fail_then_success_turns("pytest tests/test_x.py -q", 3, "")
        self.assertEqual(_kinds(_mine(turns), "struggle_arc"), [])

    def test_arc_excerpt_is_redacted_and_bounded(self):
        final = "The root cause was the token ghp_" + "a" * 36 + ". " + ("filler because words. " * 60)
        arcs = _kinds(_mine(_fail_then_success_turns("make test", 3, final)), "struggle_arc")
        self.assertEqual(len(arcs), 1)
        self.assertNotIn("ghp_" + "a" * 36, arcs[0]["excerpt"])
        self.assertLessEqual(len(arcs[0]["excerpt"]), tm.EXCERPT_MAX_CHARS)


class AbandonedWorkTests(unittest.TestCase):
    def _run_command(self, command, *, error=False):
        turns = [
            tf.user_turn("clean up"),
            tf.assistant_turn("That approach was wrong, backing it out.", tool_uses=[_bash("g1", command)]),
        ]
        if error:
            turns.append(tf.friction_turn(tool_use_id="g1", content="fatal: bad revision", exit_code=128))
        else:
            turns.append(tf.tool_result_turn(tool_use_id="g1", content="ok", exit_code=0))
        return _mine(turns)

    def test_git_revert_is_abandoned_work(self):
        found = _kinds(self._run_command("git revert abc1234"), "abandoned_work")
        self.assertEqual(len(found), 1)
        self.assertIn("git revert abc1234", found[0]["excerpt"])
        self.assertIn("backing it out", found[0]["context"])

    def test_git_reset_hard_to_a_commit_is_abandoned_work(self):
        self.assertEqual(len(_kinds(self._run_command("git reset --hard HEAD~2"), "abandoned_work")), 1)

    def test_git_global_options_and_chained_commands_are_seen(self):
        for command in (
            "git -C /work/repo reset --hard HEAD~1",
            "git -c core.editor=true revert abc1234",
            "git fetch origin && git reset --hard HEAD~3",
        ):
            with self.subTest(command=command):
                self.assertEqual(len(_kinds(self._run_command(command), "abandoned_work")), 1)

    def test_git_reset_hard_to_origin_is_a_sync_not_abandonment(self):
        self.assertEqual(_kinds(self._run_command("git reset --hard origin/main"), "abandoned_work"), [])

    def test_failed_revert_is_not_abandoned_work(self):
        self.assertEqual(_kinds(self._run_command("git revert nope", error=True), "abandoned_work"), [])

    def test_user_undo_that_is_abandoned_work_not_a_redirection(self):
        turns = [tf.assistant_turn("I rewrote the module."), tf.user_turn("Undo that, please.")]
        mined = _mine(turns)
        self.assertEqual(len(_kinds(mined, "abandoned_work")), 1)
        self.assertEqual(_kinds(mined, "redirection"), [])
        self.assertIn("rewrote the module", _kinds(mined, "abandoned_work")[0]["context"])

    def test_user_revert_word(self):
        self.assertEqual(len(_kinds(_after_work("Please revert the last commit."), "abandoned_work")), 1)

    def test_ordinary_git_commands_are_not_abandoned_work(self):
        self.assertEqual(_kinds(self._run_command("git status"), "abandoned_work"), [])

    def test_harness_text_is_not_abandoned_work(self):
        turns = [tf.user_turn("<system-reminder>revert if needed</system-reminder>", human=False)]
        self.assertEqual(_kinds(_mine(turns), "abandoned_work"), [])


class RediscoveryTests(unittest.TestCase):
    def _session(self, root, name, session_id, targets, cwd=tf.DEFAULT_CWD):
        turns = [tf.user_turn("where is the thing?")]
        for i, (tool, tinput) in enumerate(targets):
            tid = f"r{i}"
            turns.append(tf.assistant_turn("", tool_uses=[{"id": tid, "name": tool, "input": tinput}]))
            turns.append(tf.tool_result_turn(tool_use_id=tid, content="contents", exit_code=0))
        return tf.write_transcript(root / name, turns, session_id=session_id, cwd=cwd)

    def test_same_read_target_in_two_sessions_is_rediscovery(self):
        root = Path(tempfile.mkdtemp(prefix="ccgm-rediscovery-"))
        a = self._session(root, "a.jsonl", "sess-a", [("Read", {"file_path": f"{tf.DEFAULT_CWD}/lib/router.py"})])
        b = self._session(root, "b.jsonl", "sess-b", [("Read", {"file_path": f"{tf.DEFAULT_CWD}/lib/router.py"}), ("Grep", {"pattern": "route_table"})])
        bundle = tm.mine_to_evidence_bundle([a, b])
        found = [s for s in bundle["signals"] if s["kind"] == "rediscovery"]
        self.assertEqual(len(found), 1)
        self.assertIn("lib/router.py", found[0]["excerpt"])
        self.assertNotIn(tf.DEFAULT_CWD, found[0]["excerpt"])  # cwd-relative
        self.assertEqual(sorted(found[0]["session_ids"]), ["sess-a", "sess-b"])

    def test_target_in_one_session_only_is_not_rediscovery(self):
        root = Path(tempfile.mkdtemp(prefix="ccgm-rediscovery-"))
        a = self._session(root, "a.jsonl", "sess-a", [("Read", {"file_path": f"{tf.DEFAULT_CWD}/lib/router.py"})] * 3)
        b = self._session(root, "b.jsonl", "sess-b", [("Read", {"file_path": f"{tf.DEFAULT_CWD}/lib/other.py"})])
        bundle = tm.mine_to_evidence_bundle([a, b])
        self.assertEqual([s for s in bundle["signals"] if s["kind"] == "rediscovery"], [])

    def test_always_loaded_files_are_not_rediscovery(self):
        root = Path(tempfile.mkdtemp(prefix="ccgm-rediscovery-"))
        t = [("Read", {"file_path": f"{tf.DEFAULT_CWD}/CLAUDE.md"})]
        bundle = tm.mine_to_evidence_bundle([self._session(root, "a.jsonl", "sess-a", t), self._session(root, "b.jsonl", "sess-b", t)])
        self.assertEqual([s for s in bundle["signals"] if s["kind"] == "rediscovery"], [])

    def test_different_slugs_do_not_pool(self):
        root = Path(tempfile.mkdtemp(prefix="ccgm-rediscovery-"))
        other = Path(tempfile.mkdtemp(prefix="ccgm-other-repo-"))
        t = [("Glob", {"pattern": "src/**/*.ts"})]
        a = self._session(root, "a.jsonl", "sess-a", t)
        b = self._session(root, "b.jsonl", "sess-b", t, cwd=str(other))
        sessions = [tm.mine(a), tm.mine(b)]
        if sessions[0]["slug"] == sessions[1]["slug"]:
            self.skipTest("slug detection collapsed the two temp cwds")
        bundle = tm.mine_to_evidence_bundle([a, b])
        self.assertEqual([s for s in bundle["signals"] if s["kind"] == "rediscovery"], [])


class BundleSignalTests(unittest.TestCase):
    def _bundle(self, turns, max_input_tokens=tm.DEFAULT_MAX_INPUT_TOKENS):
        tmp = Path(tempfile.mkdtemp(prefix="ccgm-bundle-"))
        path = tf.write_transcript(tmp / "t.jsonl", turns)
        return tm.mine_to_evidence_bundle([path], max_input_tokens=max_input_tokens)

    def test_bundle_carries_signals_and_validates_against_schema(self):
        bundle = self._bundle([tf.assistant_turn("I used tabs."), tf.user_turn("No, never use tabs here.")])
        self.assertEqual([s["kind"] for s in bundle["signals"]], ["redirection"])
        errors = tm.validate_against_schema(bundle, json.loads((HERE.parent / "lib" / "evidence-bundle-schema.json").read_text()))
        self.assertEqual(errors, [])

    def test_quiet_session_has_empty_signals(self):
        bundle = self._bundle([tf.user_turn("hello"), tf.assistant_turn("hi")])
        self.assertEqual(bundle["signals"], [])

    def test_signals_take_budget_priority_over_friction(self):
        turns = [tf.assistant_turn("I used tabs."), tf.user_turn("No, never use tabs here.")]
        for i in range(30):
            turns.append(tf.assistant_turn("", tool_uses=[_bash(f"x{i}", f"cmd{i} --flag")]))
            turns.append(tf.friction_turn(tool_use_id=f"x{i}", content=("error detail %d " % i) * 20, exit_code=1))
        bundle = self._bundle(turns, max_input_tokens=400)
        self.assertEqual([s["kind"] for s in bundle["signals"]], ["redirection"])
        self.assertGreaterEqual(bundle["friction_cluster_count"], 1)  # the 1-exemplar floor still holds
        self.assertTrue(all(len(c["exemplars"]) == 1 for c in bundle["clusters"] if c["is_friction"]))

    def test_lowest_priority_signals_drop_first_when_signals_alone_overflow(self):
        turns = [tf.assistant_turn("ok")] + [tf.user_turn("Never use tabs, always spaces instead. " + "pad " * 20) for _ in range(40)]
        bundle = self._bundle(turns, max_input_tokens=500)
        cap = tm.MAX_SIGNALS_PER_KIND_PER_SESSION  # the per-session cap applies before the budget
        self.assertLess(len(bundle["signals"]), cap)
        self.assertGreater(bundle["signals_dropped"], 0)
        self.assertEqual(len(bundle["signals"]) + bundle["signals_dropped"], cap)

    def test_per_session_cap(self):
        turns = [tf.assistant_turn("ok")] + [
            tf.user_turn(f"No, use option {i} instead.") for i in range(tm.MAX_SIGNALS_PER_KIND_PER_SESSION + 10)
        ]
        mined = _mine(turns)
        self.assertEqual(len(_kinds(mined, "redirection")), tm.MAX_SIGNALS_PER_KIND_PER_SESSION)


class CursorCompatibilityTests(unittest.TestCase):
    def test_start_offset_mining_still_extracts_new_signals(self):
        tmp = Path(tempfile.mkdtemp(prefix="ccgm-cursor-"))
        first = tf.build_transcript([tf.user_turn("hello"), tf.assistant_turn("hi")])
        path = tmp / "t.jsonl"
        path.write_text(tf.to_jsonl(first), encoding="utf-8")
        offset = path.stat().st_size
        more = tf.build_transcript(
            [tf.user_turn("hello"), tf.assistant_turn("hi"), tf.assistant_turn("tabs it is"), tf.user_turn("No, never tabs.")]
        )[2:]
        with path.open("a", encoding="utf-8") as fh:
            fh.write(tf.to_jsonl(more))
        mined = tm.mine(path, offset)
        self.assertEqual(len(_kinds(mined, "redirection")), 1)
        self.assertIn("tabs it is", _kinds(mined, "redirection")[0]["context"])


if __name__ == "__main__":
    unittest.main()
