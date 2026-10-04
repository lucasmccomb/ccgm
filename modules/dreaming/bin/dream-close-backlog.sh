#!/usr/bin/env bash
# CCGM dreaming — one-off close of the pre-redesign proposal backlog
# (#1098 item 2.4).
#
# Replays every pending proposal (proposals/*.jsonl and *.jsonl.gz) through
# the current filters: loaded-context prefilter (already_encoded), hook-error
# routing (routed_to_autoheal) and trigger validation (trigger_invalid,
# trigger_unverified). Rows a filter drops are discarded with that reason; the
# rest are discarded `expired` with detail `pre-redesign`. See
# lib/close_backlog.py.
#
# Run by hand, once, at bring-up. Nothing schedules or installs-runs it.
#
# Usage:
#   dream-close-backlog.sh [--dry-run]   # default: print the plan, write nothing
#   dream-close-backlog.sh --apply       # write statuses + apply-audit records
#
# Env: CCGM_DREAMING_DIR (default ~/.claude/dreaming).

set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MODULE_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

exec python3 "${MODULE_ROOT}/lib/close_backlog.py" "$@"
