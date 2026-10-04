#!/usr/bin/env bash
# CCGM dreaming — memory eval harness (Epic 7).
#
# Thin runner: resolves paths, verifies python3 is on PATH, then delegates
# ALL orchestration -- task loading, isolated-config construction, the
# claude -p A/B, the graders, the mine->analyze->apply->A/B "dreamed" task,
# and the --gate contract -- to eval/memory_eval.py. Keeping this logic in
# Python (not bash) makes it directly unit-testable; see
# modules/dreaming/tests/test_memory_eval.py and test_smoke_eval.py.
#
# The default is the regression smoke (#1098 item 4.2): the 4 tasks marked
# `"smoke": true` x 2 arms (baseline, treatment) x 3 runs on the map model =
# 24 sessions, graded by deterministic checks (no judge), about $1.50, with
# per-run artifacts under evals/<date>/. `--full` runs the old 9-task,
# 3-arm, LLM-judged suite (270 sessions plus 270 judge calls, about $21).
#
# Usage:
#   dream-eval.sh [--full] [--tasks GLOB] [--runs N] [--backbone A,B]
#                 [--judge-model M] [--offline DIR [--allow-real-dir]]
#                 [--gate] [--freshness-days N] [--date YYYY-MM-DD]
#                 [--max-total-usd USD]
#
# Arm auth (#1038): with CLAUDE_CODE_OAUTH_TOKEN set (from `claude setup-token`;
# in the environment, the dreaming .env, or a file named by
# CCGM_EVAL_OAUTH_TOKEN_FILE or config optimistic_integration.eval_oauth_token_file)
# the arms bill the subscription and are recorded as eval:arm:subscription at
# $0. Otherwise they use ANTHROPIC_API_KEY.
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
# CCGM_EVAL_CLAUDE_BIN (override the `claude` binary used for live arm runs),
# CLAUDE_CODE_OAUTH_TOKEN, CCGM_EVAL_OAUTH_TOKEN_FILE (subscription auth).
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
