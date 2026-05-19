#!/usr/bin/env bash
# test-e2e-bypass-suppression.sh
#
# End-to-end test for bypass-mode classification (plan.md §5 Epic 1 +
# Epic 8). Verifies that modules/hooks/hooks/check-careful.py correctly
# distinguishes:
#
#   1. Routine `ask` decisions (rm -rf /tmp/foo) — suppressed in bypass
#      mode, preserved in default mode.
#   2. Bypass-proof hard blocks (git push --force origin main) — fire
#      even when permission_mode is bypassPermissions, exit 2 so the
#      tool call is hard-blocked regardless of session permission state.
#
# Why this matters: a regression in either direction is a security or
# productivity bug. Suppressing the wrong thing in bypass mode
# (force-push to main) leaks shared-history destruction; preserving
# routine asks in bypass mode reintroduces the permission-noise the
# user opted out of.
#
# We feed JSON stdin directly to the hook script — the same shape
# Claude Code produces in production — and inspect exit code + stdout
# + stderr.
#
# Run: bash modules/autoheal/tests/test-e2e-bypass-suppression.sh

set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MODULE_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
REPO_ROOT="$(cd "${MODULE_ROOT}/../.." && pwd)"

HOOK="${REPO_ROOT}/modules/hooks/hooks/check-careful.py"
HOOK_LIB="${REPO_ROOT}/modules/hooks/lib"

PASS=0
FAIL=0
TMPROOT="$(mktemp -d -t autoheal-bypass-e2e.XXXXXX)"
trap 'rm -rf "${TMPROOT}"' EXIT

# ---------------------------------------------------------------------------
# Assertion helpers
# ---------------------------------------------------------------------------

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

assert_empty() {
    local val="$1"
    local label="$2"
    if [ -z "${val}" ]; then
        PASS=$((PASS + 1))
    else
        FAIL=$((FAIL + 1))
        echo "FAIL: ${label}"
        echo "  expected empty, got: ${val}"
    fi
}

# ---------------------------------------------------------------------------
# Preflight
# ---------------------------------------------------------------------------

for f in "${HOOK}" "${HOOK_LIB}/hook_utils.py"; do
    if [ ! -f "${f}" ]; then
        echo "FATAL: missing required file: ${f}"
        exit 1
    fi
done

for tool in python3; do
    if ! command -v "${tool}" >/dev/null 2>&1; then
        echo "FATAL: ${tool} required on PATH"
        exit 1
    fi
done

# check-careful.py imports hook_utils from ~/.claude/lib at runtime.
# Stand up a fake HOME so the test does not depend on the real install.
FAKE_HOME="${TMPROOT}/home"
mkdir -p "${FAKE_HOME}/.claude/lib"
cp "${HOOK_LIB}/hook_utils.py" "${FAKE_HOME}/.claude/lib/hook_utils.py"

# Also write a minimal settings.json so any future hook that reads
# settings has something to find. The current check-careful.py does
# not read it but the test spec mentions setting one up.
cat > "${FAKE_HOME}/.claude/settings.json" <<'JSON'
{
  "permissions": {
    "allow": ["Bash(git status)"],
    "deny": ["Bash(rm -rf /)"]
  }
}
JSON

RC=0

run_hook() {
    # Args: input_json
    # Writes stdout to ${TMPROOT}/hook.out, stderr to ${TMPROOT}/hook.err,
    # and rc to ${TMPROOT}/hook.rc. We avoid command substitution for the
    # output because RC=$? inside a $() subshell does not propagate to the
    # caller, which silently turned exit 2 into "rc 0" in earlier drafts.
    local input="$1"
    printf '%s' "${input}" \
        | HOME="${FAKE_HOME}" python3 "${HOOK}" \
            >"${TMPROOT}/hook.out" 2>"${TMPROOT}/hook.err"
    RC=$?
}

# ---------------------------------------------------------------------------
# Case 1: bypass mode + routine destructive (`rm -rf /tmp/foo`) -> suppressed.
# Expect: rc 0, empty stdout, empty stderr.
# ---------------------------------------------------------------------------

CASE1_INPUT='{
  "session_id": "bypass-rm",
  "tool_name": "Bash",
  "tool_input": {"command": "rm -rf /tmp/foo"},
  "permission_mode": "bypassPermissions",
  "cwd": "/tmp/test-cwd"
}'

run_hook "${CASE1_INPUT}"
assert_eq "${RC}" "0" "case1 (bypass + rm -rf /tmp/foo): rc 0"
CASE1_OUT="$(cat "${TMPROOT}/hook.out")"
assert_empty "${CASE1_OUT}" "case1: empty stdout (no decision emitted)"
CASE1_ERR="$(cat "${TMPROOT}/hook.err")"
assert_empty "${CASE1_ERR}" "case1: empty stderr"

# ---------------------------------------------------------------------------
# Case 2: bypass mode + force-push to main -> bypass-proof hard block.
# Expect: rc 2, stderr explains the block.
# ---------------------------------------------------------------------------

CASE2_INPUT='{
  "session_id": "bypass-fp",
  "tool_name": "Bash",
  "tool_input": {"command": "git push --force origin main"},
  "permission_mode": "bypassPermissions",
  "cwd": "/tmp/test-cwd"
}'

# Ensure ALLOW_MAIN_COMMIT is unset; the hook bypass is gated on it being == "1".
unset ALLOW_MAIN_COMMIT 2>/dev/null || true

run_hook "${CASE2_INPUT}"
assert_eq "${RC}" "2" "case2 (bypass + force-push main): rc 2 (hard block)"
CASE2_ERR="$(cat "${TMPROOT}/hook.err")"
assert_contains "${CASE2_ERR}" "BLOCKED" "case2: stderr explains the block"
assert_contains "${CASE2_ERR}" "main" "case2: stderr mentions main"

# ---------------------------------------------------------------------------
# Case 3: default mode + routine destructive -> ask decision preserved.
# Expect: rc 0, stdout contains an 'ask' permissionDecision.
# ---------------------------------------------------------------------------

CASE3_INPUT='{
  "session_id": "default-rm",
  "tool_name": "Bash",
  "tool_input": {"command": "rm -rf /tmp/foo"},
  "permission_mode": "default",
  "cwd": "/tmp/test-cwd"
}'

run_hook "${CASE3_INPUT}"
assert_eq "${RC}" "0" "case3 (default + rm -rf /tmp/foo): rc 0"
CASE3_OUT="$(cat "${TMPROOT}/hook.out")"
assert_contains "${CASE3_OUT}" '"permissionDecision": "ask"' "case3: ask decision emitted in default mode"
assert_contains "${CASE3_OUT}" "Destructive" "case3: reason mentions 'Destructive'"

# ---------------------------------------------------------------------------
# Case 4: extra coverage — dontAsk mode + rm -rf -> suppressed (same family).
# Confirms is_bypass_mode covers all 3 bypass modes, not just bypassPermissions.
# ---------------------------------------------------------------------------

CASE4_INPUT='{
  "session_id": "dontask-rm",
  "tool_name": "Bash",
  "tool_input": {"command": "rm -rf /tmp/bar"},
  "permission_mode": "dontAsk",
  "cwd": "/tmp/test-cwd"
}'

run_hook "${CASE4_INPUT}"
assert_eq "${RC}" "0" "case4 (dontAsk + rm -rf): rc 0"
CASE4_OUT="$(cat "${TMPROOT}/hook.out")"
assert_empty "${CASE4_OUT}" "case4: empty stdout (suppressed)"

# ---------------------------------------------------------------------------
# Case 5: extra coverage — bypass + force-push to main + ALLOW_MAIN_COMMIT=1
# -> the explicit escape hatch lets it through.
# Expect: rc 0, no hard block (the destructive-check still fires but
# under bypass it suppresses to rc 0 with no output).
# ---------------------------------------------------------------------------

CASE5_INPUT='{
  "session_id": "bypass-fp-allow",
  "tool_name": "Bash",
  "tool_input": {"command": "git push --force origin main"},
  "permission_mode": "bypassPermissions",
  "cwd": "/tmp/test-cwd"
}'

# Inline this case so we can scope ALLOW_MAIN_COMMIT=1 to just the hook call.
# Same file-based redirection trick as run_hook (subshell RC isolation).
printf '%s' "${CASE5_INPUT}" \
    | ALLOW_MAIN_COMMIT=1 HOME="${FAKE_HOME}" python3 "${HOOK}" \
        >"${TMPROOT}/hook.out" 2>"${TMPROOT}/hook.err"
CASE5_RC=$?
assert_eq "${CASE5_RC}" "0" "case5 (bypass + force-push main + ALLOW_MAIN_COMMIT=1): rc 0"

# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

echo ""
echo "test-e2e-bypass-suppression.sh: ${PASS} passed, ${FAIL} failed"
[ "${FAIL}" -eq 0 ] || exit 1
exit 0
