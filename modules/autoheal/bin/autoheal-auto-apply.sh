#!/usr/bin/env bash
# autoheal-auto-apply.sh
#
# Nightly auto-apply step (#1099 Phase 4.2), chained after the analyzer in
# autoheal-daily.sh. The logic lives in lib/auto_apply.py; this wrapper resolves
# paths, keeps a per-day log, and always exits 0 so one bad night never fails
# the daily wrapper.
#
# Mode: `auto_apply_mode` in config.json, off (default) | shadow | active.
#   off     nothing runs.
#   shadow  logs a would-apply decision for every ready rule_insert row to
#           shadow/auto-apply.jsonl; changes nothing.
#   active  reverts fixes measured harmful, then applies rows that pass the gate
#           through /autoheal-review's PR path (Autoheal-Id and
#           Autoheal-Signature trailers). Allowed only after promotion
#           (/autoheal-toggle autoapply active); 3 reverts in 30 days demote it
#           back to shadow.
#
# Gate: kind rule_insert, validate() passes, >= 10 occurrences across >= 3
# sessions, target in the `auto_apply_targets` allowlist.
#
# Env overrides (tests):
#   CCGM_AUTOHEAL_CONFIG     default ~/.claude/autoheal/config.json
#   CCGM_AUTOHEAL_DIR        default ~/.claude/autoheal (ledger, shadow log)
#   CCGM_AUTOHEAL_LOGS_DIR   default ~/.claude/logs
#   CCGM_AUTOHEAL_TODAY      default today (UTC)

set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MODULE_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
AUTO_LIB="${MODULE_ROOT}/lib/auto_apply.py"
LOGS_DIR="${CCGM_AUTOHEAL_LOGS_DIR:-${HOME}/.claude/logs}"
TODAY="${CCGM_AUTOHEAL_TODAY:-$(date -u +%Y-%m-%d)}"
LOG_FILE="${LOGS_DIR}/autoheal-auto-apply-${TODAY}.log"

export CCGM_AUTOHEAL_CONFIG="${CCGM_AUTOHEAL_CONFIG:-${HOME}/.claude/autoheal/config.json}"
export CCGM_AUTOHEAL_TODAY="${TODAY}"

mkdir -p "${LOGS_DIR}"

if ! command -v python3 >/dev/null 2>&1; then
    printf '[%s] python3 not on PATH; auto-apply skipped\n' "${TODAY}" | tee -a "${LOG_FILE}" >&2
    exit 0
fi
if [ ! -f "${AUTO_LIB}" ]; then
    printf '[%s] %s missing; auto-apply skipped\n' "${TODAY}" "${AUTO_LIB}" | tee -a "${LOG_FILE}" >&2
    exit 0
fi

python3 "${AUTO_LIB}" --log "${LOG_FILE}" >/dev/null
exit 0
