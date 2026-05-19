#!/usr/bin/env bash
# permission-audit.sh
#
# Read-only static audit of CCGM hook classification vs settings.json deny list.
#
# For each hook .py file in the hooks directory:
#   - has-hook_utils: does the file contain `import hook_utils`?
#   - bypass-aware:   does the file reference `is_bypass_mode`?
#   - has-hard-block: does the file reference `hard_block`?
# Classification:
#   - bypass-suppressible: bypass-aware=YES (with or without hard_block)
#   - bypass-retained:     bypass-aware=NO and has-hard-block=YES
#   - legacy:              bypass-aware=NO and has-hard-block=NO
#
# For the settings file, count `.permissions.deny | length` and flag entries
# that appear redundant with a hook's hard_block rule.
#
# Modifies no files. bash 3.2 compatible (no associative arrays, no mapfile).
#
# Usage:
#   permission-audit.sh [--hooks-dir <path>] [--settings-file <path>] [--format text|json]
#
# Plan §5 Epic 5 / Section 1.3 (Part 1 — permission hygiene).

set -u

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

# Default hooks dir / settings file. If we appear to be running from a CCGM
# checkout (modules/hooks/hooks exists relative to the script), prefer the
# in-tree paths. Otherwise default to the installed paths.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../../.." && pwd 2>/dev/null || echo "")"

if [ -n "${REPO_ROOT}" ] && [ -d "${REPO_ROOT}/modules/hooks/hooks" ]; then
    DEFAULT_HOOKS_DIR="${REPO_ROOT}/modules/hooks/hooks"
else
    DEFAULT_HOOKS_DIR="${HOME}/.claude/hooks"
fi

if [ -n "${REPO_ROOT}" ] && [ -f "${REPO_ROOT}/modules/settings/settings.base.json" ]; then
    DEFAULT_SETTINGS_FILE="${REPO_ROOT}/modules/settings/settings.base.json"
else
    DEFAULT_SETTINGS_FILE="${HOME}/.claude/settings.json"
fi

HOOKS_DIR="${DEFAULT_HOOKS_DIR}"
SETTINGS_FILE="${DEFAULT_SETTINGS_FILE}"
FORMAT="text"

# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------

usage() {
    cat <<EOF
Usage: $0 [--hooks-dir <path>] [--settings-file <path>] [--format text|json]

Defaults:
  --hooks-dir     ${DEFAULT_HOOKS_DIR}
  --settings-file ${DEFAULT_SETTINGS_FILE}
  --format        text
EOF
}

while [ $# -gt 0 ]; do
    case "$1" in
        --hooks-dir)
            HOOKS_DIR="$2"
            shift 2
            ;;
        --settings-file)
            SETTINGS_FILE="$2"
            shift 2
            ;;
        --format)
            FORMAT="$2"
            shift 2
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            echo "ERROR: unknown argument: $1" >&2
            usage >&2
            exit 2
            ;;
    esac
done

case "${FORMAT}" in
    text|json) ;;
    *)
        echo "ERROR: --format must be 'text' or 'json' (got: ${FORMAT})" >&2
        exit 2
        ;;
esac

# ---------------------------------------------------------------------------
# Preflight
# ---------------------------------------------------------------------------

if [ ! -d "${HOOKS_DIR}" ]; then
    echo "ERROR: hooks dir does not exist: ${HOOKS_DIR}" >&2
    exit 2
fi

if [ ! -f "${SETTINGS_FILE}" ]; then
    echo "ERROR: settings file does not exist: ${SETTINGS_FILE}" >&2
    exit 2
fi

if ! command -v jq >/dev/null 2>&1; then
    echo "ERROR: jq is required but not on PATH" >&2
    exit 2
fi

# Normalize to absolute paths for the report.
HOOKS_DIR="$(cd "${HOOKS_DIR}" && pwd)"
SETTINGS_FILE_DIR="$(cd "$(dirname "${SETTINGS_FILE}")" && pwd)"
SETTINGS_FILE="${SETTINGS_FILE_DIR}/$(basename "${SETTINGS_FILE}")"

# ---------------------------------------------------------------------------
# Hook classification
# ---------------------------------------------------------------------------
#
# bash 3.2: no associative arrays, no mapfile. We use parallel indexed arrays.
# Each hook contributes one row in each array, indexed by HOOK_COUNT-1.

HOOK_NAMES=()
HOOK_CLASS=()
HOOK_NOTES=()
HOOK_HAS_UTILS=()
HOOK_BYPASS=()
HOOK_HARDBLOCK=()

count_suppressible=0
count_retained=0
count_legacy=0

# Iterate hook files in alphabetical order for stable output.
# Use a find | sort pipe + while-read to stay bash 3.2 compatible.
while IFS= read -r hook_path; do
    [ -z "${hook_path}" ] && continue
    hook_name="$(basename "${hook_path}")"

    if grep -q "import hook_utils" "${hook_path}" 2>/dev/null; then
        has_utils="YES"
    else
        has_utils="NO"
    fi

    if grep -q "is_bypass_mode" "${hook_path}" 2>/dev/null; then
        bypass_aware="YES"
    else
        bypass_aware="NO"
    fi

    if grep -q "hard_block" "${hook_path}" 2>/dev/null; then
        has_hard_block="YES"
    else
        has_hard_block="NO"
    fi

    classification=""
    notes=""

    if [ "${bypass_aware}" = "YES" ]; then
        classification="bypass-suppressible"
        if [ "${has_hard_block}" = "YES" ]; then
            notes="uses both helpers"
        else
            notes="hook_utils-aware, no hard_block"
        fi
        count_suppressible=$((count_suppressible + 1))
    elif [ "${has_hard_block}" = "YES" ]; then
        classification="bypass-retained"
        notes="hard_block, no is_bypass_mode"
        count_retained=$((count_retained + 1))
    else
        classification="legacy"
        if [ "${has_utils}" = "YES" ]; then
            notes="imports hook_utils but uses neither helper"
        else
            notes="not yet migrated to hook_utils"
        fi
        count_legacy=$((count_legacy + 1))
    fi

    HOOK_NAMES+=("${hook_name}")
    HOOK_CLASS+=("${classification}")
    HOOK_NOTES+=("${notes}")
    HOOK_HAS_UTILS+=("${has_utils}")
    HOOK_BYPASS+=("${bypass_aware}")
    HOOK_HARDBLOCK+=("${has_hard_block}")
done < <(find -L "${HOOKS_DIR}" -maxdepth 1 -name "*.py" -type f 2>/dev/null | sort)

HOOK_COUNT=${#HOOK_NAMES[@]}

# ---------------------------------------------------------------------------
# Deny list inspection
# ---------------------------------------------------------------------------

if ! jq -e . "${SETTINGS_FILE}" >/dev/null 2>&1; then
    echo "ERROR: settings file is not valid JSON: ${SETTINGS_FILE}" >&2
    exit 2
fi

DENY_COUNT="$(jq '(.permissions.deny // []) | length' "${SETTINGS_FILE}")"

# Pull entries one per line into a file (bash 3.2 has no mapfile).
DENY_TMP="$(mktemp -t permission-audit-deny.XXXXXX)"
jq -r '.permissions.deny // [] | .[]' "${SETTINGS_FILE}" > "${DENY_TMP}"

# ---------------------------------------------------------------------------
# Misalignment detection
# ---------------------------------------------------------------------------
#
# Known overlap rules:
#   - Bash(rm -rf:*) / Bash(rm -r:*)              overlaps check-careful.py destructive-rm
#   - Bash(git reset --hard:*)                    overlaps auto-approve-bash.py destructive-reset hard_block
#   - Bash(git push --force origin main:*)        overlaps check-careful.py force-push-to-main hard_block
#   - Bash(git push --force main:*)               same family
#   - Bash(git push -f main:*)                    same family
#   - Bash(git push -f origin main:*)             same family
#   - Bash(git push --force-with-lease origin main:*)  same family
#
# We only flag overlaps that are actionable signals — i.e., the corresponding
# hook is present in the hooks dir AND classified bypass-suppressible (so the
# hard_block survives bypass mode and the deny entry is redundant defense-in-
# depth that we may want to retain or prune).

MISALIGN_DENY=()       # the deny string
MISALIGN_HOOK=()       # the related hook file
MISALIGN_NOTE=()       # human-readable note

hook_present_with_class() {
    # Args: hook_name expected_classification
    local hook_name="$1"
    local expected="$2"
    local i=0
    while [ ${i} -lt ${HOOK_COUNT} ]; do
        if [ "${HOOK_NAMES[$i]}" = "${hook_name}" ]; then
            if [ "${HOOK_CLASS[$i]}" = "${expected}" ]; then
                return 0
            fi
            return 1
        fi
        i=$((i + 1))
    done
    return 1
}

hook_present_with_hard_block() {
    # Args: hook_name
    local hook_name="$1"
    local i=0
    while [ ${i} -lt ${HOOK_COUNT} ]; do
        if [ "${HOOK_NAMES[$i]}" = "${hook_name}" ]; then
            if [ "${HOOK_HARDBLOCK[$i]}" = "YES" ]; then
                return 0
            fi
            return 1
        fi
        i=$((i + 1))
    done
    return 1
}

flag_misalignment() {
    local entry="$1"
    local hook="$2"
    local note="$3"
    MISALIGN_DENY+=("${entry}")
    MISALIGN_HOOK+=("${hook}")
    MISALIGN_NOTE+=("${note}")
}

while IFS= read -r entry; do
    [ -z "${entry}" ] && continue
    case "${entry}" in
        "Bash(rm -rf:*)"|"Bash(rm -r:*)")
            if hook_present_with_hard_block "check-careful.py"; then
                flag_misalignment "${entry}" "check-careful.py" "destructive-rm rule"
            fi
            ;;
        "Bash(git reset --hard:*)")
            if hook_present_with_hard_block "auto-approve-bash.py"; then
                flag_misalignment "${entry}" "auto-approve-bash.py" "destructive-reset hard_block"
            fi
            ;;
        "Bash(git push --force origin main:*)"|"Bash(git push --force main:*)"|"Bash(git push -f main:*)"|"Bash(git push -f origin main:*)"|"Bash(git push --force-with-lease origin main:*)")
            if hook_present_with_hard_block "check-careful.py"; then
                flag_misalignment "${entry}" "check-careful.py" "force-push-to-main hard_block"
            fi
            ;;
    esac
done < "${DENY_TMP}"

MISALIGN_COUNT=${#MISALIGN_DENY[@]}

# Also flag hooks that import hook_utils but use neither helper — they're
# orphaned migrations. (Counted as "legacy" above but called out explicitly
# in the misalignment list because the orphan import is a real signal.)
i=0
while [ ${i} -lt ${HOOK_COUNT} ]; do
    if [ "${HOOK_CLASS[$i]}" = "legacy" ] && [ "${HOOK_HAS_UTILS[$i]}" = "YES" ]; then
        flag_misalignment "" "${HOOK_NAMES[$i]}" "hook imports hook_utils but uses neither is_bypass_mode nor hard_block"
    fi
    i=$((i + 1))
done
MISALIGN_COUNT=${#MISALIGN_DENY[@]}

# ---------------------------------------------------------------------------
# Render
# ---------------------------------------------------------------------------

if [ "${FORMAT}" = "json" ]; then
    # Build JSON via jq to avoid hand-rolling escaping.
    HOOKS_JSON="$(mktemp -t permission-audit-hooks.XXXXXX)"
    printf '[' > "${HOOKS_JSON}"
    i=0
    while [ ${i} -lt ${HOOK_COUNT} ]; do
        [ ${i} -gt 0 ] && printf ',' >> "${HOOKS_JSON}"
        jq -nc \
            --arg name "${HOOK_NAMES[$i]}" \
            --arg classification "${HOOK_CLASS[$i]}" \
            --arg has_hook_utils "${HOOK_HAS_UTILS[$i]}" \
            --arg bypass_aware "${HOOK_BYPASS[$i]}" \
            --arg has_hard_block "${HOOK_HARDBLOCK[$i]}" \
            --arg notes "${HOOK_NOTES[$i]}" \
            '{
              name: $name,
              classification: $classification,
              has_hook_utils: ($has_hook_utils == "YES"),
              bypass_aware: ($bypass_aware == "YES"),
              has_hard_block: ($has_hard_block == "YES"),
              notes: $notes
            }' >> "${HOOKS_JSON}"
        i=$((i + 1))
    done
    printf ']' >> "${HOOKS_JSON}"

    MISALIGN_JSON="$(mktemp -t permission-audit-misalign.XXXXXX)"
    printf '[' > "${MISALIGN_JSON}"
    i=0
    while [ ${i} -lt ${MISALIGN_COUNT} ]; do
        [ ${i} -gt 0 ] && printf ',' >> "${MISALIGN_JSON}"
        if [ -n "${MISALIGN_DENY[$i]}" ]; then
            jq -nc \
                --arg deny_entry "${MISALIGN_DENY[$i]}" \
                --arg hook "${MISALIGN_HOOK[$i]}" \
                --arg note "${MISALIGN_NOTE[$i]}" \
                '{
                  kind: "deny_overlaps_hard_block",
                  deny_entry: $deny_entry,
                  hook: $hook,
                  note: $note
                }' >> "${MISALIGN_JSON}"
        else
            jq -nc \
                --arg hook "${MISALIGN_HOOK[$i]}" \
                --arg note "${MISALIGN_NOTE[$i]}" \
                '{
                  kind: "orphan_hook_utils_import",
                  hook: $hook,
                  note: $note
                }' >> "${MISALIGN_JSON}"
        fi
        i=$((i + 1))
    done
    printf ']' >> "${MISALIGN_JSON}"

    jq -n \
        --arg hooks_dir "${HOOKS_DIR}" \
        --arg settings_file "${SETTINGS_FILE}" \
        --slurpfile hooks "${HOOKS_JSON}" \
        --argjson deny_count "${DENY_COUNT}" \
        --slurpfile misalignments "${MISALIGN_JSON}" \
        --argjson bypass_suppressible "${count_suppressible}" \
        --argjson bypass_retained "${count_retained}" \
        --argjson legacy "${count_legacy}" \
        --argjson misalignment_count "${MISALIGN_COUNT}" \
        '{
          hooks_dir: $hooks_dir,
          settings_file: $settings_file,
          hooks: $hooks[0],
          deny_count: $deny_count,
          misalignments: $misalignments[0],
          summary: {
            bypass_suppressible: $bypass_suppressible,
            bypass_retained: $bypass_retained,
            legacy: $legacy,
            deny_entries: $deny_count,
            misalignments: $misalignment_count
          }
        }'

    rm -f "${HOOKS_JSON}" "${MISALIGN_JSON}" "${DENY_TMP}"
    exit 0
fi

# Text mode.
echo "=== CCGM permission-audit ==="
echo "hooks-dir:     ${HOOKS_DIR}"
echo "settings-file: ${SETTINGS_FILE}"
echo ""
echo "--- Hook classification ---"
printf "%-34s %-22s %s\n" "HOOK_NAME" "CLASSIFICATION" "NOTES"
i=0
while [ ${i} -lt ${HOOK_COUNT} ]; do
    printf "%-34s %-22s %s\n" \
        "${HOOK_NAMES[$i]}" \
        "${HOOK_CLASS[$i]}" \
        "${HOOK_NOTES[$i]}"
    i=$((i + 1))
done

echo ""
echo "--- Deny list ---"
echo "count: ${DENY_COUNT}"

echo ""
echo "--- Misalignments ---"
if [ ${MISALIGN_COUNT} -eq 0 ]; then
    echo "(none)"
else
    i=0
    while [ ${i} -lt ${MISALIGN_COUNT} ]; do
        if [ -n "${MISALIGN_DENY[$i]}" ]; then
            echo "- deny entry \`${MISALIGN_DENY[$i]}\` overlaps with ${MISALIGN_HOOK[$i]} ${MISALIGN_NOTE[$i]}"
        else
            echo "- ${MISALIGN_HOOK[$i]}: ${MISALIGN_NOTE[$i]}"
        fi
        i=$((i + 1))
    done
fi

echo ""
echo "--- Summary ---"
echo "bypass-suppressible: ${count_suppressible}"
echo "bypass-retained:     ${count_retained}"
echo "legacy:              ${count_legacy}"
echo "deny entries:        ${DENY_COUNT}"
echo "misalignments:       ${MISALIGN_COUNT}"

rm -f "${DENY_TMP}"
exit 0
