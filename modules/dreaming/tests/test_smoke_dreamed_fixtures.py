#!/usr/bin/env python3
"""
Tests for the dreamed-01 eval fixtures (#1098 A11 item f).

The live smoke mined 0 proposals from dreamed-01: its synthetic transcripts
carried the `_synced_at` fact as bare error -> fix friction (which the miner
no longer extracts as a signal and the prefilter routes to autoheal), and the
human turns lacked the origin marker the miner requires. The fixtures now
carry the fact through a human redirection and a conclusion.

Offline: nothing here calls the network or reads the real ~/.claude.

The file name sorts after test_eval_poisoning.py and test_memory_eval.py on
purpose: those two read learnings_store constants frozen at first import, and
fail when another file that imports memory_eval is collected before them.

Run with: python3 -m pytest modules/dreaming/tests/test_smoke_dreamed_fixtures.py -q
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
FIXTURES = HERE.parent / "eval" / "tasks" / "fixtures"


sys.path.insert(0, str(HERE.parent / "eval"))
sys.path.insert(0, str(HERE.parent / "lib"))

import loaded_context as lc  # noqa: E402
import memory_eval as me  # noqa: E402
import transcript_miner as tm  # noqa: E402

SIGNAL_FILES = ["dreamed-session-1.jsonl", "dreamed-session-2.jsonl"]
NOISE_FILES = ["dreamed-noise-session-1.jsonl"]
SIGNAL_SLUG = "dreamed-fixture-repo"
NOISE_SLUG = "dreamed-noise-repo"
FACT = "_synced_at"

# What a map call returns for the signal slug: the fact, cited by the human
# redirection and the assistant's conclusion.
CANDIDATE_CONTENT = (
    "Every new database table must define a `_synced_at timestamptz` column: the replication "
    "pipeline tracks row changes through it and refuses to replicate a table without it."
)


def _bundle(files: list[str]) -> dict:
    return tm.mine_to_evidence_bundle([FIXTURES / f for f in files])


def _signal_excerpts(bundle: dict) -> list[dict]:
    return [s for s in bundle["signals"] if FACT in s["excerpt"]]


def _candidate(excerpts: list[tuple[str, str]], content: str = CANDIDATE_CONTENT) -> dict:
    return {
        "type": "pitfall",
        "content": content,
        "evidence": [{"session_id": sid, "excerpt": ex} for sid, ex in excerpts],
        "occurrence_count": len(excerpts),
        "notes": None,
    }


class FixtureSignalTests(unittest.TestCase):
    def test_each_signal_session_yields_a_redirection_and_a_conclusion_with_the_fact(self):
        for name in SIGNAL_FILES:
            with self.subTest(fixture=name):
                signals = tm.mine(FIXTURES / name)["signals"]
                kinds = {s["kind"] for s in signals if FACT in s["excerpt"]}
                self.assertEqual(kinds, {"redirection", "conclusion"})

    def test_the_bundle_carries_the_fact_as_signals_from_both_sessions(self):
        sessions = {s["session_id"] for s in _signal_excerpts(_bundle(SIGNAL_FILES))}
        self.assertEqual(sessions, {"dreamed-src-0001", "dreamed-src-0002"})

    def test_the_noise_session_yields_no_signal(self):
        self.assertEqual(tm.mine(FIXTURES / NOISE_FILES[0])["signals"], [])


class FixturePrefilterTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="ccgm-dreamed-fixtures-"))
        self.addCleanup(lambda: shutil.rmtree(self.root, ignore_errors=True))
        home = self.root / "claude"
        for sub in ("rules", "hooks", "projects"):
            (home / sub).mkdir(parents=True)
        self.roots = lc.Roots(
            claude_home=home, rules_dir=home / "rules", hooks_dir=home / "hooks",
            projects_root=home / "projects", proposals_dir=self.root / "proposals",
        )
        self.bundle = _bundle(SIGNAL_FILES)
        self.corpus = lc.build_corpus(SIGNAL_SLUG, cwds=[], roots=self.roots)

    def prefilter(self, candidate: dict):
        return lc.prefilter_candidates(
            [candidate], self.corpus, threshold=lc.DEFAULT_THRESHOLD, hook_names=set(),
            evidence_index=lc.build_evidence_index(self.bundle), friction_threshold=lc.DEFAULT_FRICTION_THRESHOLD,
        )

    def test_a_candidate_built_from_the_signals_survives_prefilter_and_routing(self):
        evidence = [(s["session_id"], s["excerpt"]) for s in _signal_excerpts(self.bundle)]
        self.assertGreaterEqual(len(evidence), 2)
        kept, dropped = self.prefilter(_candidate(evidence))
        self.assertEqual(dropped, [])
        self.assertEqual(len(kept), 1)

    def test_the_old_shape_a_candidate_citing_only_the_tool_error_is_routed_to_autoheal(self):
        friction = [
            ex["excerpt"]
            for cluster in self.bundle["clusters"] if cluster.get("is_friction")
            for ex in cluster.get("exemplars", []) if FACT in ex["excerpt"]
        ]
        self.assertTrue(friction, "fixture lost its tool-error friction")
        restated = "replicate: ERROR: table is missing required column _synced_at; the replication pipeline cannot track a table without a _synced_at timestamptz cursor column"
        kept, dropped = self.prefilter(_candidate([("dreamed-src-0001", friction[0])], content=restated))
        self.assertEqual(kept, [])
        self.assertEqual(dropped[0]["reason"], lc.ROUTED_TO_AUTOHEAL)


class MiningArtifactTests(unittest.TestCase):
    """The eval keeps its mining stages so a no-lift result is diagnosable."""

    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="ccgm-dreamed-artifacts-"))
        self.addCleanup(lambda: shutil.rmtree(self.root, ignore_errors=True))
        keys = ("CCGM_DREAMING_CLAUDE_HOME", "CCGM_DREAMING_ENV_FILE", "CCGM_DREAMING_AUTOHEAL_ENV_FILE")
        previous = {k: os.environ.get(k) for k in keys}

        def restore():
            for k, v in previous.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v
            me.set_run_context(None)

        self.addCleanup(restore)
        os.environ["CCGM_DREAMING_CLAUDE_HOME"] = str(self.root / "claude-home")
        os.environ["CCGM_DREAMING_ENV_FILE"] = str(self.root / "none.env")
        os.environ["CCGM_DREAMING_AUTOHEAL_ENV_FILE"] = str(self.root / "none-autoheal.env")

        self.projects = self.root / "claude-projects"
        for slug, files in ((SIGNAL_SLUG, SIGNAL_FILES), (NOISE_SLUG, NOISE_FILES)):
            me._write_transcript_corpus({"slug": slug, "files": files}, projects_root=self.projects, fixtures_dir=FIXTURES)

        # Canned map responses: the signal slug maps the fact, the noise slug nothing.
        offline = self.root / "offline"
        offline.mkdir()
        sessions = sorted({s["session_id"] for s in _signal_excerpts(_bundle(SIGNAL_FILES))})
        excerpts = {s["session_id"]: s["excerpt"] for s in _signal_excerpts(_bundle(SIGNAL_FILES))}
        cand = _candidate([(sid, excerpts[sid]) for sid in sessions])
        self._write_response(offline / f"map-{SIGNAL_SLUG}.json", {"candidates": [cand]})
        self._write_response(offline / f"map-{NOISE_SLUG}.json", {"candidates": []})
        self._write_response(offline / "reduce.json", {"proposals": []})
        self.offline = offline

    @staticmethod
    def _write_response(path: Path, payload: dict) -> None:
        path.write_text(json.dumps({
            "id": "msg_fixture", "type": "message", "role": "assistant", "model": "claude-fixture",
            "stop_reason": "end_turn", "usage": {"input_tokens": 100, "output_tokens": 50},
            "content": [{"type": "text", "text": json.dumps(payload)}],
        }), encoding="utf-8")

    def _run(self) -> Path:
        state = self.root / "dreaming-state"
        capture: dict = {}
        with me._learnings_store_pointed_at(self.root / "learnings", claude_projects_dir=self.projects):
            proposals = me._mine_and_analyze(
                slugs=[SIGNAL_SLUG, NOISE_SLUG], projects_root=self.projects, dreaming_state_dir=state,
                offline_dir=self.offline, api_key=None, force_day="2026-10-04", capture=capture,
            )
        self.capture = capture
        self.state = state
        return proposals

    def test_capture_holds_signals_map_output_and_kept_candidates(self):
        self._run()
        self.assertTrue(any(FACT in s["excerpt"] for s in self.capture["signals"][SIGNAL_SLUG]))
        self.assertEqual(len(self.capture["map_output"][SIGNAL_SLUG]), 1)
        self.assertEqual(self.capture["map_output"][NOISE_SLUG], [])
        self.assertEqual(len(self.capture["kept"][SIGNAL_SLUG]), 1)

    def test_write_mining_artifacts_persists_each_stage(self):
        proposals = self._run()
        me.set_run_context(me.RunContext(artifact_dir=self.root / "evals" / "2026-10-04"))
        me.write_mining_artifacts(
            "dreamed-01-pipeline-end-to-end", proposals_path=proposals, applied_info={"applied": False},
            injected_facts=[], capture=self.capture,
            run_summary_path=self.state / "state" / "runs" / "2026-10-04.json",
        )
        mining = self.root / "evals" / "2026-10-04" / "dreamed-01-pipeline-end-to-end" / "mining"
        signals = json.loads((mining / "signals.json").read_text(encoding="utf-8"))
        map_output = json.loads((mining / "map-output.json").read_text(encoding="utf-8"))
        prefilter = json.loads((mining / "prefilter.json").read_text(encoding="utf-8"))
        self.assertTrue(any(FACT in s["excerpt"] for s in signals[SIGNAL_SLUG]))
        self.assertIn(FACT, map_output[SIGNAL_SLUG][0]["content"])
        self.assertEqual(prefilter["candidates_mapped"], 1)
        self.assertEqual(len(prefilter["kept"][SIGNAL_SLUG]), 1)
        self.assertEqual(prefilter["dropped"], [])
        self.assertEqual((prefilter["map_calls"], prefilter["reduce_calls"]), (2, 1))
        self.assertTrue((mining / "proposals.jsonl").is_file())
        self.assertTrue((mining / "applied.json").is_file())

    def test_a_dropped_candidate_is_recorded_with_its_reason(self):
        # A candidate that restates a rule the session already loads is dropped;
        # the artifact must say so.
        rules = self.root / "claude-home" / "rules"
        rules.mkdir(parents=True)
        (rules / "schema.md").write_text(CANDIDATE_CONTENT + "\n", encoding="utf-8")
        proposals = self._run()
        me.set_run_context(me.RunContext(artifact_dir=self.root / "evals" / "2026-10-04"))
        me.write_mining_artifacts(
            "dreamed-01-pipeline-end-to-end", proposals_path=proposals, applied_info={"applied": False},
            injected_facts=[], capture=self.capture,
            run_summary_path=self.state / "state" / "runs" / "2026-10-04.json",
        )
        mining = self.root / "evals" / "2026-10-04" / "dreamed-01-pipeline-end-to-end" / "mining"
        prefilter = json.loads((mining / "prefilter.json").read_text(encoding="utf-8"))
        self.assertEqual([d["reason"] for d in prefilter["dropped"]], [lc.ALREADY_ENCODED])
        self.assertEqual(prefilter["kept"].get(SIGNAL_SLUG, []), [])
        self.assertEqual(prefilter["reduce_calls"], 0)


if __name__ == "__main__":
    unittest.main()
