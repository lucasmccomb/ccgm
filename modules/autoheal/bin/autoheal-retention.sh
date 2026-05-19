#!/usr/bin/env bash
# autoheal-retention.sh
#
# Retention sweep (plan.md §1.3, §5 Epic 12).
#
# For each autoheal subdirectory that holds date-named records
# (events/, proposals/, digests/, applied/, sent/):
#   - Files older than retention_gzip_days that are NOT yet gzipped →
#     gzip in place (file.jsonl → file.jsonl.gz).
#   - Files older than retention_delete_days that ARE gzipped (or that
#     otherwise pass the deletion age threshold) → delete.
#
# Idempotent: a second run on the same state produces no further changes
# and emits no errors. Achieved via:
#   - `gzip -f` only on files we have already confirmed are NOT .gz
#   - delete predicate scoped to *.gz so already-gzipped files are the
#     only deletion candidates (we never delete uncompressed records)
#   - find -mtime +N is monotone: a file that was below the threshold
#     yesterday cannot drop below today; once moved to .gz we don't
#     touch the new mtime since we delete based on the .gz file's age
#     too (gzip preserves mtime via -n + system default behavior)
#
# Env overrides (for tests):
#   CCGM_AUTOHEAL_DIR              default ~/.claude/autoheal
#   CCGM_AUTOHEAL_CONFIG           default $CCGM_AUTOHEAL_DIR/config.json
#   CCGM_AUTOHEAL_RETENTION_GZIP   default from config (30)
#   CCGM_AUTOHEAL_RETENTION_DELETE default from config (60)
#
# Exit codes:
#   0  always (failures on individual files are logged to stderr but the
#      sweep continues; we never block the pipeline)

set -u

AUTOHEAL_DIR="${CCGM_AUTOHEAL_DIR:-${HOME}/.claude/autoheal}"
CONFIG_FILE="${CCGM_AUTOHEAL_CONFIG:-${AUTOHEAL_DIR}/config.json}"

# Read thresholds from config (defaults 30/60). Env overrides win.
GZIP_DAYS="${CCGM_AUTOHEAL_RETENTION_GZIP:-}"
DELETE_DAYS="${CCGM_AUTOHEAL_RETENTION_DELETE:-}"

if [ -z "${GZIP_DAYS}" ] || [ -z "${DELETE_DAYS}" ]; then
    if [ -f "${CONFIG_FILE}" ] && command -v jq >/dev/null 2>&1; then
        if [ -z "${GZIP_DAYS}" ]; then
            GZIP_DAYS="$(jq -r '.retention_gzip_days // 30' "${CONFIG_FILE}" 2>/dev/null || echo 30)"
        fi
        if [ -z "${DELETE_DAYS}" ]; then
            DELETE_DAYS="$(jq -r '.retention_delete_days // 60' "${CONFIG_FILE}" 2>/dev/null || echo 60)"
        fi
    fi
fi

# Numeric guard.
case "${GZIP_DAYS}" in
    ''|*[!0-9]*) GZIP_DAYS=30 ;;
esac
case "${DELETE_DAYS}" in
    ''|*[!0-9]*) DELETE_DAYS=60 ;;
esac

if [ ! -d "${AUTOHEAL_DIR}" ]; then
    # Nothing to do. Fresh install or test run with no autoheal yet.
    echo "autoheal-retention: ${AUTOHEAL_DIR} not present; nothing to do" >&2
    exit 0
fi

# Directories with date-named records that participate in retention.
SUBDIRS=(events proposals digests applied sent)

gzipped=0
deleted=0
errors=0

# Phase 1: gzip files older than GZIP_DAYS that are not yet compressed.
#
# We restrict to known suffixes (.jsonl, .md, .log, .flag) so we don't
# accidentally compress lock sidecars or partial files. The .flag files
# are size-0 sentinel files; gzipping them is wasteful but harmless and
# keeps the policy uniform.
for sub in "${SUBDIRS[@]}"; do
    dir="${AUTOHEAL_DIR}/${sub}"
    [ -d "${dir}" ] || continue

    # find -mtime +N: strictly older than N*24h.
    while IFS= read -r path; do
        [ -z "${path}" ] && continue
        # Skip if already gzipped (defensive; the -name filters above
        # already exclude .gz, but a future caller passing CCGM_AUTOHEAL_*
        # could change the policy).
        case "${path}" in
            *.gz) continue ;;
        esac
        if gzip -f -- "${path}" 2>/dev/null; then
            gzipped=$((gzipped + 1))
        else
            errors=$((errors + 1))
            echo "autoheal-retention: gzip failed for ${path}" >&2
        fi
    done < <(find "${dir}" -maxdepth 1 -type f \
        \( -name '*.jsonl' -o -name '*.md' -o -name '*.log' -o -name '*.flag' \) \
        -mtime "+${GZIP_DAYS}" 2>/dev/null)
done

# Phase 2: delete gzipped files older than DELETE_DAYS.
for sub in "${SUBDIRS[@]}"; do
    dir="${AUTOHEAL_DIR}/${sub}"
    [ -d "${dir}" ] || continue

    while IFS= read -r path; do
        [ -z "${path}" ] && continue
        if rm -f -- "${path}" 2>/dev/null; then
            deleted=$((deleted + 1))
        else
            errors=$((errors + 1))
            echo "autoheal-retention: rm failed for ${path}" >&2
        fi
    done < <(find "${dir}" -maxdepth 1 -type f -name '*.gz' \
        -mtime "+${DELETE_DAYS}" 2>/dev/null)
done

echo "autoheal-retention: gzipped=${gzipped} deleted=${deleted} errors=${errors} (gzip>${GZIP_DAYS}d, delete>${DELETE_DAYS}d)" >&2
exit 0
