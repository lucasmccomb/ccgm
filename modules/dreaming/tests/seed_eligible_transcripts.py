#!/usr/bin/env python3
"""Seed the synthetic transcript(s) the enabled-mode chain smoke needs
(composite-eligibility plan.md §8.3 precondition 3 / E4 fixture triple part a).

Writes one synthetic Claude Code session transcript under a projects-root the
smoke passes on argv[1]. The transcript:
  * has its cwd basename == "eligible-demo", so detect_project_slug() resolves it
    to the same slug the offline reduce fixture's learning_add cites;
  * carries a HUMAN-origin correction sequence, so the apply-time tier re-mining
    mints the "user-corrected" tier;
  * contains the corroboration sentence the reduce fixture's excerpt matches
    verbatim, so §3.4's excerpt check passes;
  * is dated a few days ago (recent embedded timestamps) so recency is healthy.

100% synthetic (transcript_fixtures.py; no real path/username/transcript). This
is the ONE row that must reach ELIGIBLE (decision_basis="composite") for the
smoke's positive assertion; every signal is set so it clears the gate with margin.

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
CWD = f"/synthetic-nonexistent/code/{SLUG}"
CORROBORATION = (
    "The Edit tool does not follow symlinks so read the workspace path first "
    "before editing the file"
)


def seed(projects_root: str, *, days_ago: float = 2.0) -> Path:
    base = datetime.now(timezone.utc) - timedelta(days=days_ago)
    turns = tf.correction_sequence(
        request="Please edit the installed hook file directly.",
        correction="No, that's wrong, revert that -- the Edit tool did not follow the symlink.",
    )
    # A separate human turn carrying the exact corroboration sentence the reduce
    # fixture's excerpt cites verbatim.
    turns.append(tf.user_turn(CORROBORATION, human=True))
    path = Path(projects_root) / "proj-eligible-demo" / f"{SESSION_ID}.jsonl"
    tf.write_transcript(path, turns, session_id=SESSION_ID, cwd=CWD, base_ts=tf.iso(base))
    return path


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("usage: seed_eligible_transcripts.py <projects_root_dir>", file=sys.stderr)
        raise SystemExit(2)
    written = seed(sys.argv[1])
    print(str(written))
