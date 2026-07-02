#!/usr/bin/env bash
# CCGM dreaming -- read-only auto-memory reconciliation (Epic 8).
#
# Compares Claude Code's own auto-memory (~/.claude/projects/*/memory/)
# against the CCGM learnings store via lib/reconcile_automemory.py, then
# APPENDS the resulting "## Reconciliation" section to the day's digest
# markdown (~/.claude/dreaming/digests/{date}.md). Never writes to the
# auto-memory directory itself -- reconcile_automemory.py is read-only by
# construction (see modules/dreaming/tests/test_reconcile_automemory.py's
# write-guard test).
#
# Called by dream-daily.sh's chain as step 3, with ZERO arguments
# (`run_step "reconcile" "${BIN_DIR}/dream-reconcile.sh"` -- no
# --force-day, no positional date). Day resolution therefore cannot read
# --force-day directly the way dream-digest.sh's own positional arg does
# (dream-daily.sh forwards TODAY only to the digest step, not this one).
# Falls back, in order:
#   1. An explicit [YYYY-MM-DD] argument (manual/standalone invocation,
#      mirrors dream-digest.sh's own convention).
#   2. CCGM_DREAMING_TODAY, if set.
#   3. The digest file with the newest mtime under
#      ~/.claude/dreaming/digests/ -- dream-digest.sh (chain step 2)
#      always runs immediately before this step (chain step 3) and just
#      wrote that day's digest, so its mtime is the freshest file in the
#      directory at the moment this script runs. This is deliberately
#      mtime-based, not filename-lexicographic: --force-day can target a
#      date in the PAST relative to other existing digests, so "the digest
#      most RECENTLY WRITTEN" (mtime) is the correct signal, not "the
#      digest naming the latest date" (filename sort would pick the wrong
#      file under --force-day).
#   4. Today (UTC), matching dream-digest.sh's own final fallback.
#
# Usage:
#   dream-reconcile.sh [YYYY-MM-DD]
#
# Env overrides (tests):
#   CCGM_DREAMING_DIR            default ~/.claude/dreaming
#   CCGM_DREAMING_TODAY          default unset
#   CCGM_DREAMING_PROJECTS_ROOT  default unset -- forwarded to
#                                 reconcile_automemory.py's --projects-root
#                                 when set (default otherwise: real
#                                 ~/.claude/projects, via HOME)
#
# Exit codes:
#   0  reconciliation appended (including the "nothing to reconcile" case)
#   2  invariant violation (python3 missing, bad date argument, or
#      reconcile_automemory.py itself failed)

set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MODULE_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

DATE_ARG="${1:-}"
DREAMING_DIR="${CCGM_DREAMING_DIR:-${HOME}/.claude/dreaming}"
DIGESTS_DIR="${DREAMING_DIR}/digests"

if ! command -v python3 >/dev/null 2>&1; then
    echo "dream-reconcile: python3 not found on PATH" >&2
    exit 2
fi

# ---------------------------------------------------------------------
# Day resolution (see header comment for the fallback chain). Delegated
# to python for portable, exact date validation and portable mtime
# comparison (avoids `stat -f` vs `stat -c` shell dialect differences
# between macOS and Linux CI).
# ---------------------------------------------------------------------

TARGET_DATE="$(python3 - "${DATE_ARG}" "${CCGM_DREAMING_TODAY:-}" "${DIGESTS_DIR}" <<'PYEOF'
import datetime as dt
import glob
import os
import sys

date_arg, today_env, digests_dir = sys.argv[1], sys.argv[2], sys.argv[3]


def valid(d):
    try:
        dt.date.fromisoformat(d)
        return True
    except (ValueError, TypeError):
        return False


if date_arg:
    if not valid(date_arg):
        print(f"dream-reconcile: '{date_arg}' is not a valid YYYY-MM-DD date", file=sys.stderr)
        sys.exit(2)
    print(date_arg)
    sys.exit(0)

if today_env and valid(today_env):
    print(today_env)
    sys.exit(0)

candidates = []
if os.path.isdir(digests_dir):
    for path in glob.glob(os.path.join(digests_dir, "*.md")):
        base = os.path.splitext(os.path.basename(path))[0]
        if valid(base):
            try:
                candidates.append((os.path.getmtime(path), base))
            except OSError:
                continue

if candidates:
    candidates.sort()
    print(candidates[-1][1])
    sys.exit(0)

print(dt.datetime.now(dt.timezone.utc).date().isoformat())
PYEOF
)"
RC=$?
if [ ${RC} -ne 0 ] || [ -z "${TARGET_DATE}" ]; then
    exit 2
fi

mkdir -p "${DIGESTS_DIR}"
DIGEST_FILE="${DIGESTS_DIR}/${TARGET_DATE}.md"
if [ ! -f "${DIGEST_FILE}" ]; then
    printf '# Dreaming digest -- %s\n\n' "${TARGET_DATE}" >"${DIGEST_FILE}"
fi

PROJECTS_ROOT_ARGS=()
if [ -n "${CCGM_DREAMING_PROJECTS_ROOT:-}" ]; then
    PROJECTS_ROOT_ARGS=(--projects-root "${CCGM_DREAMING_PROJECTS_ROOT}")
fi

SECTION="$(python3 "${MODULE_ROOT}/lib/reconcile_automemory.py" "${PROJECTS_ROOT_ARGS[@]}")"
PY_RC=$?
if [ ${PY_RC} -ne 0 ]; then
    echo "dream-reconcile: reconcile_automemory.py failed (exit ${PY_RC})" >&2
    exit 2
fi

# Idempotent append: strip any existing "## Reconciliation" section left by
# a prior run against this SAME digest file before appending the freshly
# computed one, so re-running this script (e.g. `dream-daily.sh
# --force-day <date>` re-run while smoke testing, per dreaming.md's own
# "Quick checks") always yields exactly one section instead of duplicating
# it. Mirrors dream-digest.sh's own idempotent full-overwrite semantics,
# but scoped to just this one section -- dream-reconcile.sh does not own
# the rest of the digest file (header, canary banner, proposals, tally
# belong to dream-digest.sh, chain step 2). Delegated to python for the
# same BSD-vs-GNU portability reason the date resolution above already
# documents (no sed/awk -i dialect differences between macOS and Linux CI).
CCGM_RECONCILE_DIGEST_FILE="${DIGEST_FILE}" CCGM_RECONCILE_SECTION="${SECTION}" python3 - <<'PYEOF'
import os
import re

digest_file = os.environ["CCGM_RECONCILE_DIGEST_FILE"]
section = os.environ["CCGM_RECONCILE_SECTION"]

with open(digest_file, "r", encoding="utf-8") as fh:
    content = fh.read()

# The Reconciliation section runs from its own "## Reconciliation" heading
# up to (but not including) the next top-level "## " heading, or end of
# file when it is the last section (the common case -- this step always
# runs last in dream-daily.sh's chain, after dream-digest.sh). re.sub
# replaces every non-overlapping match, so this also self-heals a digest
# that was already duplicated by a pre-fix run.
content = re.sub(r"\n?## Reconciliation\n.*?(?=\n## |\Z)", "", content, flags=re.DOTALL)

content = content.rstrip("\n") + "\n\n" + section.rstrip("\n") + "\n"

with open(digest_file, "w", encoding="utf-8") as fh:
    fh.write(content)
PYEOF
PY_APPEND_RC=$?
if [ ${PY_APPEND_RC} -ne 0 ]; then
    echo "dream-reconcile: failed to write reconciliation section (exit ${PY_APPEND_RC})" >&2
    exit 2
fi

echo "reconciliation appended: ${DIGEST_FILE}" >&2
exit 0
