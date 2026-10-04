#!/usr/bin/env python3
"""
Subagent transcripts (#1098 Phase 3, round 3). Claude Code writes each
subagent's transcript to <project>/<session-id>/subagents/agent-*.jsonl. The
miner must discover those files, resolve their slug from their own cwd
(including removed worktrees), never read their first turn as a human, and
carry the parent session id. All fixtures are synthetic.

Run with: python3 -m pytest modules/dreaming/tests/test_subagent_transcripts.py -q
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "lib"))
sys.path.insert(0, str(HERE))

import transcript_miner as tm  # noqa: E402
import transcript_fixtures as tf  # noqa: E402

PARENT = "11111111-2222-3333-4444-555555555555"


def _init_repo(parent: Path, name: str, remote: str) -> Path:
    repo = parent / name
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "remote", "add", "origin", remote], cwd=repo, check=True)
    return repo


class SubagentTestCase(unittest.TestCase):
    def setUp(self):
        self._env = {k: os.environ.pop(k, None) for k in ("CCGM_LEARNINGS_PROJECT", "CCGM_LEARNINGS_DIR")}
        self.tmp = Path(tempfile.mkdtemp(prefix="ccgm-subagent-"))
        self.root = self.tmp / "projects"
        self.project = self.root / "-encoded-cwd"
        self.repo = _init_repo(self.tmp, "widget-repo", "https://example.test/fixtureorg/widget-repo.git")
        self.slug = tm.detect_project_slug(str(self.repo))
        dreaming = self.tmp / "dreaming"
        self._prev_dreaming = os.environ.get("CCGM_DREAMING_DIR")
        os.environ["CCGM_DREAMING_DIR"] = str(dreaming)

    def tearDown(self):
        for k, v in self._env.items():
            if v is not None:
                os.environ[k] = v
        if self._prev_dreaming is None:
            os.environ.pop("CCGM_DREAMING_DIR", None)
        else:
            os.environ["CCGM_DREAMING_DIR"] = self._prev_dreaming

    def top_level(self, turns=None, cwd=None):
        turns = turns or [tf.user_turn("hello"), tf.assistant_turn("hi")]
        return tf.write_transcript(self.project / f"{PARENT}.jsonl", turns, session_id=PARENT, cwd=cwd or str(self.repo))

    def subagent(self, name="agent-aaa", turns=None, cwd=None):
        turns = turns or [tf.user_turn("do the unit"), tf.assistant_turn("done")]
        return tf.write_transcript(
            self.project / PARENT / "subagents" / f"{name}.jsonl", turns, session_id=PARENT, cwd=cwd or str(self.repo)
        )


class DiscoveryTests(SubagentTestCase):
    def test_subagent_file_is_discovered(self):
        top = self.top_level()
        sub = self.subagent()
        due = tm.discover([self.slug], projects_root=self.root, lookback_days=365)
        self.assertEqual(sorted(due), sorted([str(top), str(sub)]))

    def test_only_real_transcript_jsonl_is_discovered(self):
        self.top_level()
        self.subagent()
        sub_dir = self.project / PARENT / "subagents"
        (sub_dir / "agent-aaa.meta.json").write_text('{"agentType": "general-purpose"}', encoding="utf-8")
        tool_results = self.project / PARENT / "tool-results"
        tool_results.mkdir()
        (tool_results / "out.jsonl").write_text(json.dumps({"type": "user", "cwd": str(self.repo)}) + "\n", encoding="utf-8")
        deeper = sub_dir / "nested"
        deeper.mkdir()
        (deeper / "agent-deep.jsonl").write_text(json.dumps({"type": "user", "cwd": str(self.repo)}) + "\n", encoding="utf-8")
        found = {Path(p).name for p in tm.discover([self.slug], projects_root=self.root, lookback_days=365)}
        self.assertEqual(found, {f"{PARENT}.jsonl", "agent-aaa.jsonl"})

    def test_subagent_slug_resolves_from_its_own_cwd(self):
        other = _init_repo(self.tmp, "other-repo", "https://example.test/fixtureorg/other-repo.git")
        self.subagent("agent-mine")
        self.subagent("agent-theirs", cwd=str(other))
        mine = tm.discover([self.slug], projects_root=self.root, lookback_days=365)
        self.assertEqual([Path(p).name for p in mine], ["agent-mine.jsonl"])

    def test_removed_worktree_cwd_resolves_to_the_repos_slug(self):
        gone = self.repo / ".claude" / "worktrees" / "agent-abc123"  # never created: torn down after merge
        self.assertFalse(gone.exists())
        sub = self.subagent(cwd=str(gone))
        self.assertEqual(tm.mine(sub)["slug"], self.slug)
        self.assertEqual(tm.discover([self.slug], projects_root=self.root, lookback_days=365), [str(sub)])

    def test_live_worktree_cwd_resolves_to_the_repos_slug(self):
        live = self.repo / ".claude" / "worktrees" / "agent-live"
        live.mkdir(parents=True)
        self.assertEqual(tm.mine(self.subagent(cwd=str(live)))["slug"], self.slug)

    def test_cursors_apply_per_subagent_file(self):
        sub = self.subagent()
        end = sub.stat().st_size
        cursors = {str(sub): {"slug": self.slug, "offset": end}}
        self.assertEqual(tm.discover([self.slug], cursors=cursors, projects_root=self.root, lookback_days=365), [])
        with sub.open("a", encoding="utf-8") as fh:
            fh.write(tf.to_jsonl(tf.build_transcript([tf.assistant_turn("later")], session_id=PARENT, cwd=str(self.repo), base_ts="2026-02-01T00:00:00.000Z")))
        due = tm.discover_with_offsets([self.slug], cursors=cursors, projects_root=self.root, lookback_days=365)
        self.assertEqual(due, {str(sub): end})

    def test_migration_seeds_cursors_for_subagent_files(self):
        top = self.top_level()
        sub = self.subagent()
        tm.write_watermark(self.slug, "2030-01-01T00:00:00.000Z")  # after every line in both files
        self.assertEqual(tm.read_cursors(), {})
        tm.migrate_watermarks_to_cursors([self.slug], projects_root=self.root)
        cursors = tm.read_cursors()
        self.assertEqual(set(cursors), {str(top), str(sub)})
        self.assertEqual(cursors[str(sub)]["offset"], sub.stat().st_size)
        self.assertEqual(tm.discover([self.slug], cursors=cursors, projects_root=self.root, lookback_days=365), [])

    def test_unseeded_subagent_files_stay_inside_the_lookback_window(self):
        sub = self.subagent()
        old = 1_000_000_000  # year 2001
        os.utime(sub, (old, old))
        self.assertEqual(tm.discover([self.slug], projects_root=self.root, lookback_days=7), [])


class SubagentMiningTests(SubagentTestCase):
    def test_parent_session_id_is_recorded(self):
        self.assertEqual(tm.mine(self.subagent())["parent_session_id"], PARENT)
        self.assertIsNone(tm.mine(self.top_level())["parent_session_id"])

    def test_bundle_session_summary_carries_the_parent_id(self):
        sub = self.subagent(turns=[
            tf.user_turn("go"),
            tf.assistant_turn("", tool_uses=[{"id": "t1", "name": "Bash", "input": {"command": "make"}}]),
            tf.friction_turn(tool_use_id="t1", content="boom", exit_code=2),
        ])
        bundle = tm.mine_to_evidence_bundle([sub])
        self.assertEqual(bundle["sessions"][0]["parent_session_id"], PARENT)
        schema = json.loads((HERE.parent / "lib" / "evidence-bundle-schema.json").read_text())
        self.assertEqual(tm.validate_against_schema(bundle, schema), [])

    def test_no_user_turn_of_a_subagent_is_a_redirection(self):
        # The dispatcher's prompt can carry the human-origin markers and
        # redirect-sounding words. It is still not a human.
        turns = [
            tf.user_turn("Never use tabs; always use spaces instead. I want a small diff."),
            tf.assistant_turn("Working on it."),
            tf.user_turn("No, that's wrong, use two spaces instead."),
            tf.assistant_turn("Fixed."),
        ]
        mined = tm.mine(self.subagent(turns=turns))
        self.assertEqual([s for s in mined["signals"] if s["kind"] in ("redirection", "abandoned_work")], [])
        self.assertEqual(mined["user_corrections"], [])

    def test_the_same_turns_in_a_top_level_session_still_count(self):
        turns = [tf.user_turn("Do it."), tf.assistant_turn("Done."), tf.user_turn("No, that's wrong, use two spaces instead.")]
        mined = tm.mine(self.top_level(turns))
        self.assertEqual(len([s for s in mined["signals"] if s["kind"] == "redirection"]), 1)

    def test_friction_arcs_and_conclusions_apply_to_subagents(self):
        turns = [tf.user_turn("get tests passing")]
        for i in range(3):
            turns.append(tf.assistant_turn("again", tool_uses=[{"id": f"f{i}", "name": "Bash", "input": {"command": "pytest tests/test_x.py -q"}}]))
            turns.append(tf.friction_turn(tool_use_id=f"f{i}", content="FAILED tests/test_x.py::test_a", exit_code=1))
        turns.append(tf.assistant_turn("", tool_uses=[{"id": "ok", "name": "Bash", "input": {"command": "pytest tests/test_x.py -q"}}]))
        turns.append(tf.tool_result_turn(tool_use_id="ok", content="1 passed", exit_code=0))
        turns.append(tf.assistant_turn("The root cause was a stale fixture path in the snapshot directory for this suite."))
        mined = tm.mine(self.subagent(turns=turns))
        kinds = {s["kind"] for s in mined["signals"]}
        self.assertIn("struggle_arc", kinds)
        self.assertEqual(len(mined["friction_events"]), 3)


if __name__ == "__main__":
    unittest.main()
