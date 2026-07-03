#!/usr/bin/env bash
# CCGM dreaming — weekly observability scorecard renderer.
#
# Renders a deterministic weekly scorecard over the read-path signals that are
# ALREADY recorded on disk (captured / injected / reused / applied / store
# health) to ~/.claude/dreaming/scorecards/{week-ending}.md, then prints that
# path on stdout.
#
# This wrapper is deliberately thin: it resolves the window + generated-at wall
# clock (the ONLY place a wall-clock read is allowed -- lib/scorecard.py never
# calls Date.now) and hands them to scorecard.render(), which does all the
# read-only aggregation. Mirrors dream-digest.sh's lib/bin split and its
# tm._import_sibling_module() path for reaching the self-improving module's
# learnings_store.
#
# Usage:
#   dream-scorecard.sh [YYYY-MM-DD]   # week-ending date; defaults to today (UTC)
#
# The window is the 7 calendar days ending on (and including) the week-ending
# date: [week_ending-6d 00:00Z, week_ending+1d 00:00Z).
#
# Exit codes:
#   0  scorecard rendered (path printed on stdout)
#   2  invariant violation (python3 missing, bad date argument, renderer error)

set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MODULE_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

DATE_ARG="${1:-}"

if ! command -v python3 >/dev/null 2>&1; then
    echo "dream-scorecard: python3 not found on PATH" >&2
    exit 2
fi

if [ -n "${DATE_ARG}" ]; then
    if ! python3 -c "import datetime as dt, sys; dt.date.fromisoformat(sys.argv[1])" "${DATE_ARG}" 2>/dev/null; then
        echo "dream-scorecard: '${DATE_ARG}' is not a valid YYYY-MM-DD date" >&2
        exit 2
    fi
    WEEK_ENDING="${DATE_ARG}"
else
    WEEK_ENDING="${CCGM_DREAMING_TODAY:-$(python3 -c 'import datetime; print(datetime.datetime.now(datetime.timezone.utc).date().isoformat())')}"
fi

DREAMING_DIR="${CCGM_DREAMING_DIR:-${HOME}/.claude/dreaming}"
LEARNINGS_DIR="${CCGM_LEARNINGS_DIR:-${HOME}/.claude/learnings}"
INJECTION_LOG_DIR="${DREAMING_DIR}/injection-log"
PROPOSALS_DIR="${DREAMING_DIR}/proposals"
APPLY_AUDIT_FILE="${DREAMING_DIR}/state/apply-audit.jsonl"
SCORECARDS_DIR="${DREAMING_DIR}/scorecards"

mkdir -p "${SCORECARDS_DIR}"

OUTPUT="$(
    CCGM_SC_WEEK_ENDING="${WEEK_ENDING}" \
    CCGM_SC_LEARNINGS_DIR="${LEARNINGS_DIR}" \
    CCGM_SC_INJECTION_LOG_DIR="${INJECTION_LOG_DIR}" \
    CCGM_SC_PROPOSALS_DIR="${PROPOSALS_DIR}" \
    CCGM_SC_APPLY_AUDIT_FILE="${APPLY_AUDIT_FILE}" \
    CCGM_SC_MODULE_ROOT="${MODULE_ROOT}" \
    python3 - <<'PYEOF'
import os
import sys
from datetime import datetime, time, timedelta, timezone

module_root = os.environ["CCGM_SC_MODULE_ROOT"]
sys.path.insert(0, os.path.join(module_root, "lib"))

import scorecard  # noqa: E402  (dreaming lib, just inserted on sys.path)
# learnings_store lives in a DIFFERENT module's lib/ dir (self-improving);
# reuse transcript_miner's established installed-or-sibling import helper
# rather than re-deriving the path (same pattern as dream-digest.sh).
import transcript_miner as tm  # noqa: E402
learnings_store = tm._import_sibling_module(  # noqa: SLF001
    "self-improving", "learnings_store",
    "projection (_project_lines) + effective_confidence for store-health scoring",
)

week_ending = datetime.strptime(os.environ["CCGM_SC_WEEK_ENDING"], "%Y-%m-%d").date()
# Half-open 7-day window ending on (and including) week_ending.
window_end = datetime.combine(week_ending + timedelta(days=1), time.min, tzinfo=timezone.utc)
window_start = window_end - timedelta(days=7)
# Wall-clock reads live HERE (the wrapper), never in the library.
generated_at = datetime.now(timezone.utc)

md = scorecard.render(
    window_start,
    window_end,
    learnings_dir=os.environ["CCGM_SC_LEARNINGS_DIR"],
    injection_log_dir=os.environ["CCGM_SC_INJECTION_LOG_DIR"],
    proposals_dir=os.environ["CCGM_SC_PROPOSALS_DIR"],
    apply_audit_path=os.environ["CCGM_SC_APPLY_AUDIT_FILE"],
    store_api=learnings_store,
    generated_at=generated_at,
)
sys.stdout.write(md)
PYEOF
)"

py_exit=$?
if [ ${py_exit} -ne 0 ]; then
    echo "dream-scorecard: renderer failed (exit ${py_exit})" >&2
    exit 2
fi

SCORECARD_FILE="${SCORECARDS_DIR}/${WEEK_ENDING}.md"
printf '%s\n' "${OUTPUT}" > "${SCORECARD_FILE}"
echo "scorecard written: ${SCORECARD_FILE}" >&2
echo "${SCORECARD_FILE}"
exit 0
