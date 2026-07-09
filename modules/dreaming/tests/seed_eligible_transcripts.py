#!/usr/bin/env python3
"""Seed the synthetic transcript(s) the enabled-mode chain smoke needs
(composite-eligibility plan.md §8.3 precondition 3 / E4 fixture triple part a).

Writes TWO synthetic Claude Code session transcripts under a projects-root the
smoke passes on argv[1]. Each transcript:
  * has its cwd basename == "eligible-demo", so detect_project_slug() resolves it
    to the same slug the offline reduce fixture's learning_add cites;
  * carries a HUMAN-origin correction sequence, so the apply-time tier re-mining
    mints the "user-corrected" tier;
  * contains the corroboration sentence the reduce fixture's excerpt matches
    verbatim, so §3.4's excerpt check passes;
  * is dated a few days ago (recent embedded timestamps) so recency is healthy.

The two sessions exercise the multi-session citation path (#853): the offline
reduce fixture cites session 0001 only while claiming prevalence.sessions=2, and
the offline map candidate lists BOTH session ids, so dream_analyze's
deterministic post-reduce enrichment attaches session 0002's (miner-derived,
corroborating) excerpt -- and the apply-time gate then verifies TWO sessions.
Both sessions share the same friction command so they cluster together, and each
carries a user-correction, so either session_id resolves to a transcript-derived
bundle excerpt the enrichment can attach and the gate can corroborate.

100% synthetic (transcript_fixtures.py; no real path/username/transcript). This
is the row that must reach ELIGIBLE (decision_basis="composite") for the smoke's
positive assertion; every signal is set so it clears the gate with margin.

Usage: python3 seed_eligible_transcripts.py <projects_root_dir>
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import transcript_fixtures as tf  # noqa: E402

SLUG = "eligible-demo"
SESSION_ID = "sess-eligible-demo-0001"
SESSION_ID_2 = "sess-eligible-demo-0002"
CWD = f"/synthetic-nonexistent/code/{SLUG}"
CORROBORATION = (
    "The Edit tool does not follow symlinks so read the workspace path first "
    "before editing the file"
)


def _session_turns() -> list:
    turns = tf.correction_sequence(
        request="Please edit the installed hook file directly.",
        correction="No, that's wrong, revert that -- the Edit tool did not follow the symlink.",
    )
    # A separate human turn carrying the exact corroboration sentence the reduce
    # fixture's excerpt cites verbatim.
    turns.append(tf.user_turn(CORROBORATION, human=True))
    return turns


def seed(projects_root: str, *, days_ago: float = 2.0) -> list[Path]:
    base = datetime.now(timezone.utc) - timedelta(days=days_ago)
    written: list[Path] = []
    for subdir, session_id in (
        ("proj-eligible-demo", SESSION_ID),
        ("proj-eligible-demo-b", SESSION_ID_2),
    ):
        path = Path(projects_root) / subdir / f"{session_id}.jsonl"
        tf.write_transcript(
            path, _session_turns(), session_id=session_id, cwd=CWD, base_ts=tf.iso(base)
        )
        written.append(path)
    return written


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("usage: seed_eligible_transcripts.py <projects_root_dir>", file=sys.stderr)
        raise SystemExit(2)
    for p in seed(sys.argv[1]):
        print(str(p))
