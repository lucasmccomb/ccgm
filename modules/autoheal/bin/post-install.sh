#!/usr/bin/env bash
# CCGM autoheal — post-install hook (Epic 6).
#
# Called by start.sh on `--reinstall autoheal`. Idempotent: re-runs
# autoheal-install.sh only when the LaunchAgent is missing OR the
# config.json is missing. Otherwise it is a no-op, so re-installing
# the module never clobbers user state.

set -u
set -o pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MODULE_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

AUTOHEAL_DIR="${CCGM_AUTOHEAL_DIR:-${HOME}/.claude/autoheal}"
USERNAME="${CCGM_AUTOHEAL_USERNAME:-${USER:-unknown}}"
LABEL="com.${USERNAME}.ccgm.autoheal.daily"

NEEDS_INSTALL=0

if [ ! -f "${AUTOHEAL_DIR}/config.json" ]; then
    NEEDS_INSTALL=1
fi

# Use sched_platform.list_scheduled_jobs to detect a missing LaunchAgent
# rather than poking at the plist path directly — Linux v2 would not
# share the plist filename convention.
SCHED_LIB_DIR=""
for candidate in \
    "${HOME}/.claude/lib" \
    "$(cd "${MODULE_ROOT}/../hooks/lib" 2>/dev/null && pwd)"; do
    if [ -n "${candidate}" ] && [ -f "${candidate}/sched_platform.py" ]; then
        SCHED_LIB_DIR="${candidate}"
        break
    fi
done

if [ -n "${SCHED_LIB_DIR}" ]; then
    HAS_JOB="$(python3 - <<PY
import sys

sys.path.insert(0, "${SCHED_LIB_DIR}")
import sched_platform

try:
    jobs = sched_platform.list_scheduled_jobs()
except NotImplementedError:
    # Linux v2: pretend we have the job so post-install is a no-op.
    print("yes")
    sys.exit(0)
except Exception:
    print("no")
    sys.exit(0)

print("yes" if "${LABEL}" in jobs else "no")
PY
)"
    if [ "${HAS_JOB}" != "yes" ]; then
        NEEDS_INSTALL=1
    fi
fi

if [ "${NEEDS_INSTALL}" -eq 1 ]; then
    echo "autoheal post-install: state missing; running autoheal-install.sh"
    exec bash "${MODULE_ROOT}/bin/autoheal-install.sh"
fi

echo "autoheal post-install: already installed; no-op."
