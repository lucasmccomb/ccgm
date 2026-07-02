#!/usr/bin/env bash
# CCGM dreaming — nightly analyzer (Epic 3).
#
# Thin runner: resolves paths, verifies python3 (and curl, unless --offline
# is set) are on PATH, then delegates ALL orchestration -- config/.env
# loading, mining, preflight cost planning, map/reduce calls, proposal
# validation/sanitization/fingerprinting, watermark advancement, and
# proposals-file + run-summary writes -- to dream_analyze.py. Keeping this
# logic in Python (not bash) makes it directly unit-testable; see
# modules/dreaming/tests/test_dream_analyze.py.
#
# Usage:
#   dream-analyze.sh [--force-day YYYY-MM-DD] [--offline DIR] [--dry-run]
#                     [--slugs A,B,C] [--projects-root DIR]
#
# Env vars (all optional; see lib/dream_analyze.py path helpers for the
# full list): CCGM_DREAMING_DIR, CCGM_DREAMING_CONFIG, CCGM_DREAMING_TODAY,
# CCGM_DREAMING_ENV_FILE, CCGM_DREAMING_AUTOHEAL_ENV_FILE,
# CCGM_LEARNINGS_DIR, CCGM_CLAUDE_PROJECTS_DIR.
#
# Exit codes (propagated from dream_analyze.py):
#   0  success, including "nothing to do" and "no API key configured"
#   1  fatal error (bad prompts/schema files, curl transport failure,
#      reduce phase never parseable after its retry -- see
#      state/canary.json's reduce_failures for which slug(s); no
#      watermark advance and no proposals write happen on this path)
#   2  daily cost cap reached before any slug could be processed

set -u
set -o pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MODULE_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

OFFLINE=0
for arg in "$@"; do
    case "${arg}" in
        --offline|--offline=*) OFFLINE=1 ;;
    esac
done

if ! command -v python3 >/dev/null 2>&1; then
    echo "dream-analyze: python3 not found on PATH" >&2
    exit 1
fi

if [ "${OFFLINE}" -eq 0 ] && ! command -v curl >/dev/null 2>&1; then
    echo "dream-analyze: curl not found on PATH (required unless --offline is given)" >&2
    exit 1
fi

DREAMING_DIR="${CCGM_DREAMING_DIR:-${HOME}/.claude/dreaming}"
mkdir -p "${DREAMING_DIR}/proposals" "${DREAMING_DIR}/digests" "${DREAMING_DIR}/state/runs"

exec python3 "${MODULE_ROOT}/lib/dream_analyze.py" "$@"
