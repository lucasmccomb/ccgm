#!/usr/bin/env bash
# CCGM dreaming — memory eval harness (Epic 7).
#
# Thin runner: resolves paths, verifies python3 is on PATH, then delegates
# ALL orchestration -- task loading, isolated-config construction, the
# three-arm claude -p A/B, the blind judge, the four-bucket classifier, the
# mine->analyze->apply->A/B "dreamed" task, and the --gate contract -- to
# eval/memory_eval.py. Keeping this logic in Python (not bash) makes it
# directly unit-testable; see modules/dreaming/tests/test_memory_eval.py.
#
# Usage:
#   dream-eval.sh [--tasks GLOB] [--runs N] [--backbone A,B] [--judge-model M]
#                 [--offline DIR [--allow-real-dir]] [--gate] [--freshness-days N]
#                 [--date YYYY-MM-DD]
#
# Every path the harness writes (evals/ results and markers, cost.log)
# resolves from CCGM_DREAMING_DIR, default ~/.claude/dreaming. An --offline
# run never writes that live default: it moves to a fresh temp dir unless
# CCGM_DREAMING_DIR names another dir or --allow-real-dir is given. A live
# run (no --offline) and --gate use the dir as given.
#
# Env vars (all optional; see eval/memory_eval.py path helpers for the full
# list): CCGM_DREAMING_DIR, CCGM_DREAMING_TODAY, CCGM_DREAMING_ENV_FILE,
# CCGM_DREAMING_AUTOHEAL_ENV_FILE, CCGM_LEARNINGS_DIR, CCGM_CLAUDE_PROJECTS_DIR,
# CCGM_EVAL_CLAUDE_BIN (override the `claude` binary used for live arm runs).
#
# Exit codes:
#   0  success (including "no API key configured, skipped" and, in --gate
#      mode, "gate open")
#   1  no tasks matched the glob; the `claude` binary could not be resolved;
#      every agent run of the eval failed to execute (the harness is broken,
#      so no results file is written -- the first failure's raw output is on
#      stderr and an evals/<date>.harness-broken marker pauses --gate until
#      a run produces results, #1027); or (in --gate mode) "gate closed"
#   3  (--gate mode) "gate paused" -- see the printed JSON `code` and
#      `reason` fields (#1098 item 2.1)

set -u
set -o pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MODULE_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

if ! command -v python3 >/dev/null 2>&1; then
    echo "dream-eval: python3 not found on PATH" >&2
    exit 1
fi

exec python3 "${MODULE_ROOT}/eval/memory_eval.py" "$@"
