#!/usr/bin/env bash
# CCGM autoheal — uninstaller (Epic 6).
#
# Removes the LaunchAgent via `sched_platform.uninstall_scheduled_job`
# and (when explicitly requested) clears the autoheal state directory.
# Default is to PRESERVE user data — we error on the side of "the user
# can re-enable later without losing history".
#
# Flags:
#   --purge-data   Remove ~/.claude/autoheal entirely after uninstall.
#                  Without this flag, state is left in place.
#
# Env overrides (tests):
#   CCGM_AUTOHEAL_DIR        Root of autoheal state.
#   CCGM_AUTOHEAL_USERNAME   Override $USER for the label.

set -u
set -o pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MODULE_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

PURGE_DATA=0
for arg in "$@"; do
    case "${arg}" in
        --purge-data)
            PURGE_DATA=1
            ;;
        *)
            echo "autoheal-uninstall: unknown flag: ${arg}" >&2
            exit 1
            ;;
    esac
done

AUTOHEAL_DIR="${CCGM_AUTOHEAL_DIR:-${HOME}/.claude/autoheal}"
USERNAME="${CCGM_AUTOHEAL_USERNAME:-${USER:-unknown}}"
LABEL="com.${USERNAME}.ccgm.autoheal.daily"

SCHED_LIB_DIR=""
for candidate in \
    "${HOME}/.claude/lib" \
    "$(cd "${MODULE_ROOT}/../hooks/lib" 2>/dev/null && pwd)"; do
    if [ -n "${candidate}" ] && [ -f "${candidate}/sched_platform.py" ]; then
        SCHED_LIB_DIR="${candidate}"
        break
    fi
done

if [ -z "${SCHED_LIB_DIR}" ]; then
    echo "autoheal-uninstall: cannot locate sched_platform.py; treating as already uninstalled." >&2
else
    python3 - <<PY
import sys

sys.path.insert(0, "${SCHED_LIB_DIR}")
import sched_platform

try:
    sched_platform.uninstall_scheduled_job("${LABEL}")
    print("OK: uninstalled ${LABEL}")
except NotImplementedError as exc:
    print(f"DEFERRED: {exc}", file=sys.stderr)
except Exception as exc:
    print(f"WARN: uninstall raised: {exc}", file=sys.stderr)
PY
fi

if [ "${PURGE_DATA}" -eq 1 ]; then
    echo "autoheal-uninstall: purging ${AUTOHEAL_DIR}"
    rm -rf "${AUTOHEAL_DIR}"
else
    echo "autoheal-uninstall: state preserved at ${AUTOHEAL_DIR} (pass --purge-data to remove)"
fi
