#!/usr/bin/env bash
# Test suite for modules/autoheal/hooks/post-prompt-introspect.py
# AND the apply-path subroutine in modules/autoheal/lib/apply-proposal.py.
#
# Scenarios for post-prompt-introspect.py:
#   1. Friction repro: 2 permission_request events for the same
#      tool+command prefix in this session => suggestion emitted.
#   2. Dedup: same scenario, fire Stop twice => second fire silent.
#   3. Empty events file => no suggestion.
#   4. Cross-session: 1 friction event in current session + 2 in a
#      different session => no suggestion (must be >= 2 in current).
#   5. tool_failure events repro: same prefix, kind=tool_failure => suggestion.
#   6. Distinct prefixes: 1 git push + 1 git status => no suggestion.
#
# Scenarios for apply-proposal.py:
#   7. resolve_clone_root walks up to find start.sh.
#   8. find_proposal returns None for missing id.
#   9. find_proposal returns the matching record by id.
#
# Run: bash modules/autoheal/tests/test-post-prompt-introspect.sh

set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MODULE_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
HOOK="${MODULE_ROOT}/hooks/post-prompt-introspect.py"
APPLY_LIB="${MODULE_ROOT}/lib/apply-proposal.py"

PASS=0
FAIL=0

assert_eq() {
    local actual="$1"
    local expected="$2"
    local label="$3"
    if [ "${actual}" = "${expected}" ]; then
        PASS=$((PASS + 1))
    else
        FAIL=$((FAIL + 1))
        echo "FAIL: ${label}"
        echo "  expected: ${expected}"
        echo "  actual:   ${actual}"
    fi
}

assert_contains() {
    local haystack="$1"
    local needle="$2"
    local label="$3"
    case "${haystack}" in
        *"${needle}"*)
            PASS=$((PASS + 1))
            ;;
        *)
            FAIL=$((FAIL + 1))
            echo "FAIL: ${label}"
            echo "  expected substring: ${needle}"
            echo "  actual: ${haystack}"
            ;;
    esac
}

assert_not_contains() {
    local haystack="$1"
    local needle="$2"
    local label="$3"
    case "${haystack}" in
        *"${needle}"*)
            FAIL=$((FAIL + 1))
            echo "FAIL: ${label}"
            echo "  unexpected substring: ${needle}"
            echo "  actual: ${haystack}"
            ;;
        *)
            PASS=$((PASS + 1))
            ;;
    esac
}

# Isolated sandbox for events + seen sentinel files.
EVENTS_DIR="$(mktemp -d -t autoheal_events.XXXXXX)"
SEEN_DIR="$(mktemp -d -t autoheal_seen.XXXXXX)"
trap 'rm -rf "${EVENTS_DIR}" "${SEEN_DIR}"' EXIT

# Pin a deterministic "today" so the test does not race the clock at midnight UTC.
TODAY="2026-05-18"
EVENTS_FILE="${EVENTS_DIR}/${TODAY}.jsonl"

# Helper: run the hook with isolated env. Pass session id via stdin JSON.
run_hook() {
    local session_id="$1"
    CCGM_AUTOHEAL_EVENTS_DIR="${EVENTS_DIR}" \
        CCGM_AUTOHEAL_SEEN_DIR="${SEEN_DIR}" \
        CCGM_AUTOHEAL_TODAY="${TODAY}" \
        python3 "${HOOK}" <<EOF 2>&1 1>/dev/null
{"session_id": "${session_id}"}
EOF
}

# Helper: append a JSONL event to the events file.
write_event() {
    local kind="$1"
    local session="$2"
    local tool="$3"
    local cmd="$4"
    local rec
    rec=$(python3 -c "
import json, sys
print(json.dumps({
    'kind': '${kind}',
    'timestamp': '2026-05-18T14:00:00Z',
    'session_id': '${session}',
    'tool_name': '${tool}',
    'redacted_command': '${cmd}',
}))
")
    echo "${rec}" >> "${EVENTS_FILE}"
}

# ---------- Scenario 1: friction repro --------------------------------
> "${EVENTS_FILE}"
rm -f "${SEEN_DIR}/"*
SESSION_1="sess-friction-001"
write_event "permission_request" "${SESSION_1}" "Bash" "git push --force origin feat-x"
write_event "permission_request" "${SESSION_1}" "Bash" "git push --force origin feat-y"
out=$(run_hook "${SESSION_1}")
assert_contains "${out}" "<autoheal-suggestion>" "scenario 1: suggestion emitted on 2nd same-signature event"
assert_contains "${out}" "/permission-fix latest" "scenario 1: suggestion references /permission-fix latest"
# Bash tool name should appear in the paraphrased message; full command must NOT.
assert_contains "${out}" "Bash" "scenario 1: tool name appears in suggestion"
assert_not_contains "${out}" "feat-y" "scenario 1: verbatim command tail not echoed"

# ---------- Scenario 2: dedup -----------------------------------------
# The seen sentinel from scenario 1 already exists; re-run should be silent.
out=$(run_hook "${SESSION_1}")
assert_not_contains "${out}" "<autoheal-suggestion>" "scenario 2: duplicate Stop fire suppresses suggestion"

# ---------- Scenario 3: empty events ----------------------------------
> "${EVENTS_FILE}"
rm -f "${SEEN_DIR}/"*
SESSION_3="sess-empty-001"
out=$(run_hook "${SESSION_3}")
assert_not_contains "${out}" "<autoheal-suggestion>" "scenario 3: empty events file produces no suggestion"

# ---------- Scenario 4: cross-session ---------------------------------
> "${EVENTS_FILE}"
rm -f "${SEEN_DIR}/"*
SESSION_4="sess-current-001"
SESSION_4_OTHER="sess-other-002"
write_event "permission_request" "${SESSION_4}" "Bash" "git push --force origin feat-z"
write_event "permission_request" "${SESSION_4_OTHER}" "Bash" "git push --force origin main"
write_event "permission_request" "${SESSION_4_OTHER}" "Bash" "git push --force origin feat-a"
out=$(run_hook "${SESSION_4}")
assert_not_contains "${out}" "<autoheal-suggestion>" "scenario 4: cross-session friction does not trigger"

# ---------- Scenario 5: tool_failure repro ----------------------------
> "${EVENTS_FILE}"
rm -f "${SEEN_DIR}/"*
SESSION_5="sess-toolfail-001"
write_event "tool_failure" "${SESSION_5}" "Bash" "npm run lint"
write_event "tool_failure" "${SESSION_5}" "Bash" "npm run lint --fix"
out=$(run_hook "${SESSION_5}")
assert_contains "${out}" "<autoheal-suggestion>" "scenario 5: repeated tool_failure triggers suggestion"

# ---------- Scenario 6: distinct prefixes -----------------------------
> "${EVENTS_FILE}"
rm -f "${SEEN_DIR}/"*
SESSION_6="sess-distinct-001"
write_event "permission_request" "${SESSION_6}" "Bash" "git push --force origin feat-1"
write_event "permission_request" "${SESSION_6}" "Bash" "git status --short"
out=$(run_hook "${SESSION_6}")
assert_not_contains "${out}" "<autoheal-suggestion>" "scenario 6: distinct command prefixes do not trigger"

# ---------- Scenario 7: resolve_clone_root walks up -------------------
ROOT_TMP="$(mktemp -d -t apply_root.XXXXXX)"
trap 'rm -rf "${EVENTS_DIR}" "${SEEN_DIR}" "${ROOT_TMP}"' EXIT
touch "${ROOT_TMP}/start.sh"
mkdir -p "${ROOT_TMP}/deep/deeper"
out=$(python3 -c "
import importlib.util, sys
spec = importlib.util.spec_from_file_location('ap', '${APPLY_LIB}')
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
print(mod._resolve_clone_root('${ROOT_TMP}/deep/deeper'))
")
assert_eq "${out}" "${ROOT_TMP}" "scenario 7: _resolve_clone_root walks up to start.sh"

# ---------- Scenario 8: find_proposal missing -------------------------
PROPOSALS_DIR="$(mktemp -d -t autoheal_proposals.XXXXXX)"
trap 'rm -rf "${EVENTS_DIR}" "${SEEN_DIR}" "${ROOT_TMP}" "${PROPOSALS_DIR}"' EXIT
out=$(CCGM_AUTOHEAL_PROPOSALS_DIR="${PROPOSALS_DIR}" CCGM_AUTOHEAL_TODAY="${TODAY}" python3 -c "
import importlib.util
spec = importlib.util.spec_from_file_location('ap', '${APPLY_LIB}')
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
print(mod._find_proposal('prop_nope'))
")
assert_eq "${out}" "None" "scenario 8: _find_proposal returns None for missing id"

# ---------- Scenario 9: find_proposal hit -----------------------------
cat > "${PROPOSALS_DIR}/${TODAY}.jsonl" <<'EOF'
{"id":"prop_001","kind":"settings_allow_add","title":"add wrangler"}
{"id":"prop_002","kind":"settings_allow_add","title":"add supabase"}
EOF
out=$(CCGM_AUTOHEAL_PROPOSALS_DIR="${PROPOSALS_DIR}" CCGM_AUTOHEAL_TODAY="${TODAY}" python3 -c "
import importlib.util
spec = importlib.util.spec_from_file_location('ap', '${APPLY_LIB}')
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
prop = mod._find_proposal('prop_002')
print(prop['title'] if prop else 'MISS')
")
assert_eq "${out}" "add supabase" "scenario 9: _find_proposal returns matching record by id"

# ---------- Scenario 10: stop_hook_active short-circuits --------------
> "${EVENTS_FILE}"
rm -f "${SEEN_DIR}/"*
SESSION_10="sess-loop-001"
write_event "permission_request" "${SESSION_10}" "Bash" "git push --force origin feat-a"
write_event "permission_request" "${SESSION_10}" "Bash" "git push --force origin feat-b"
out=$(CCGM_AUTOHEAL_EVENTS_DIR="${EVENTS_DIR}" \
    CCGM_AUTOHEAL_SEEN_DIR="${SEEN_DIR}" \
    CCGM_AUTOHEAL_TODAY="${TODAY}" \
    python3 "${HOOK}" <<EOF 2>&1 1>/dev/null
{"session_id": "${SESSION_10}", "stop_hook_active": true}
EOF
)
assert_not_contains "${out}" "<autoheal-suggestion>" "scenario 10: stop_hook_active suppresses suggestion"

echo ""
echo "test-post-prompt-introspect.sh: ${PASS} passed, ${FAIL} failed"
[ "${FAIL}" -eq 0 ] || exit 1
exit 0
