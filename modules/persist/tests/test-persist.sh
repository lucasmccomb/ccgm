#!/usr/bin/env bash
# Tests for the persist module: the Stop hook (persist-stop.py) and the
# ccgm-persist CLI. Every guard must let the stop through; an active, fresh,
# same-session state must block.
#
# Run: bash modules/persist/tests/test-persist.sh

set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MODULE_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
HOOK="${MODULE_ROOT}/hooks/persist-stop.py"
CLI="${MODULE_ROOT}/bin/ccgm-persist"

PASS=0
FAIL=0
pass() { PASS=$((PASS + 1)); }
failed() {
    FAIL=$((FAIL + 1))
    echo "FAIL: $1"
    if [ -n "${2:-}" ]; then echo "  $2"; fi
}

unset CLAUDE_CODE_SESSION_ID CLAUDE_PROJECT_DIR

TMP="$(mktemp -d)"
trap 'chmod -R u+rwx "${TMP}" 2>/dev/null; rm -rf "${TMP}"' EXIT
export HOME="${TMP}/home"
mkdir -p "${HOME}/.claude/persist"
DIR="${HOME}/.claude/persist"
SID="sess-aaa"

write_state() {
    # $1 sid, $2 iteration, $3 max
    cat > "${DIR}/$1.json" <<JSON
{"task":"ship the thing","iteration":$2,"max_iterations":$3,"started_at":"2026-01-01T00:00:00Z","done_criteria":"tests pass"}
JSON
}

run_hook() { printf '%s' "$1" | python3 "${HOOK}" 2>/dev/null; }

assert_allows() {
    # $1 label, $2 input json
    local out
    out="$(run_hook "$2")"
    if printf '%s' "${out}" | grep -q '"decision"[[:space:]]*:[[:space:]]*"block"'; then
        failed "$1" "blocked: ${out}"
    else
        pass
    fi
}

assert_blocks() {
    local out
    out="$(run_hook "$2")"
    if printf '%s' "${out}" | grep -q '"decision"[[:space:]]*:[[:space:]]*"block"'; then
        pass
    else
        failed "$1" "expected block, got: ${out}"
    fi
}

field() {
    # $1 file, $2 key
    python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get(sys.argv[2]))' "$1" "$2"
}

reset() { rm -f "${DIR}"/*; write_state "${SID}" 0 5; }

STOP="{\"session_id\":\"${SID}\"}"

# --- baseline -------------------------------------------------------------
reset
assert_blocks "active state blocks" "${STOP}"
out="$(run_hook "${STOP}")"
case "${out}" in *"ccgm-persist --session ${SID} done"*) pass ;; *) failed "reason names the done command" "${out}" ;; esac
case "${out}" in *"fresh evidence"*) pass ;; *) failed "reason demands fresh evidence" "${out}" ;; esac
case "${out}" in *"tests pass"*) pass ;; *) failed "reason carries done_criteria" "${out}" ;; esac
[ "$(field "${DIR}/${SID}.json" iteration)" = "2" ] && pass || failed "iteration increments per block" "$(field "${DIR}/${SID}.json" iteration)"

rm -f "${DIR}"/*
assert_allows "no state allows (opt-in)" "${STOP}"

# --- guard 1: stop_hook_active ---------------------------------------------
reset
assert_allows "guard 1 stop_hook_active" "{\"session_id\":\"${SID}\",\"stop_hook_active\":true}"

# --- guard 2: context-limit stop ---------------------------------------------
reset
assert_allows "guard 2 context limit" "{\"session_id\":\"${SID}\",\"stop_reason\":\"context_limit\"}"
assert_allows "guard 2 max_tokens" "{\"session_id\":\"${SID}\",\"stop_reason\":\"max_tokens\"}"

# --- guard 3: transcript context at or above 95% ----------------------------
reset
printf '{"usage":{"input_tokens":196000},"context_window":200000}\n' > "${TMP}/t-high.jsonl"
assert_allows "guard 3 transcript context high" "{\"session_id\":\"${SID}\",\"transcript_path\":\"${TMP}/t-high.jsonl\"}"
printf '{"usage":{"input_tokens":20000},"context_window":200000}\n' > "${TMP}/t-low.jsonl"
assert_blocks "guard 3 low context still blocks" "{\"session_id\":\"${SID}\",\"transcript_path\":\"${TMP}/t-low.jsonl\"}"

# --- guard 4: user abort -------------------------------------------------------
reset
assert_allows "guard 4 user abort (reason)" "{\"session_id\":\"${SID}\",\"stop_reason\":\"user_interrupt\"}"
assert_allows "guard 4 user abort (exact)" "{\"session_id\":\"${SID}\",\"stop_reason\":\"abort\"}"
assert_allows "guard 4 user_requested" "{\"session_id\":\"${SID}\",\"user_requested\":true}"

# --- guard 5: auth errors -------------------------------------------------------
reset
assert_allows "guard 5 auth error (reason)" "{\"session_id\":\"${SID}\",\"stop_reason\":\"authentication_error\"}"
assert_allows "guard 5 401" "{\"session_id\":\"${SID}\",\"stop_reason\":\"HTTP 401\"}"
assert_allows "guard 5 403 end_turn_reason" "{\"session_id\":\"${SID}\",\"end_turn_reason\":\"403 forbidden\"}"

# --- guard 6: stale state ---------------------------------------------------------
reset
touch -t 202001010000 "${DIR}/${SID}.json"
assert_allows "guard 6 stale state (>2h)" "${STOP}"
reset
python3 - "${DIR}/${SID}.json" <<'PY'
import os, sys, time
t = time.time() - 3600
os.utime(sys.argv[1], (t, t))
PY
assert_blocks "guard 6 1h-old state still blocks" "${STOP}"

# --- guard 7: iteration cap ---------------------------------------------------------
reset
write_state "${SID}" 5 5
assert_allows "guard 7 cap reached allows" "${STOP}"
[ "$(field "${DIR}/${SID}.json" active)" = "False" ] && pass || failed "guard 7 deactivates state" "active=$(field "${DIR}/${SID}.json" active)"
assert_allows "guard 7 stays off after deactivation" "${STOP}"
write_state "${SID}" 200 5000
assert_allows "guard 7 hard max (200) beats a larger max_iterations" "${STOP}"

# --- guard 8: cancel signal --------------------------------------------------------
reset
touch "${DIR}/${SID}.cancel"
assert_allows "guard 8 cancel signal allows" "${STOP}"
[ ! -e "${DIR}/${SID}.json" ] && pass || failed "guard 8 clears state"
[ ! -e "${DIR}/${SID}.cancel" ] && pass || failed "guard 8 clears signal"

# --- guard 9: other session / project ------------------------------------------------
reset
assert_allows "guard 9 different session id" '{"session_id":"sess-bbb"}'
assert_allows "guard 9 missing session id" '{}'
assert_allows "guard 9 unsafe session id" '{"session_id":"../../etc/passwd"}'
[ "$(field "${DIR}/${SID}.json" iteration)" = "0" ] && pass || failed "guard 9 leaves other state untouched"
python3 - "${DIR}/${SID}.json" <<'PY'
import json, sys
p = sys.argv[1]; s = json.load(open(p)); s["project"] = "/proj/a"; json.dump(s, open(p, "w"))
PY
out="$(printf '%s' "${STOP}" | CLAUDE_PROJECT_DIR=/proj/b python3 "${HOOK}" 2>/dev/null)"
case "${out}" in *block*) failed "guard 9 different project allows" "${out}" ;; *) pass ;; esac
out="$(printf '%s' "${STOP}" | CLAUDE_PROJECT_DIR=/proj/a python3 "${HOOK}" 2>/dev/null)"
case "${out}" in *block*) pass ;; *) failed "same project blocks" "${out}" ;; esac

# --- fail open on bad input / state -----------------------------------------------------
reset
assert_allows "garbage stdin" "not json"
assert_allows "empty stdin" ""
printf 'not json' > "${DIR}/${SID}.json"
assert_allows "corrupt state allows" "${STOP}"
printf '[1,2]' > "${DIR}/${SID}.json"
assert_allows "non-object state allows" "${STOP}"
printf '{"task":"x","iteration":"many","max_iterations":null}' > "${DIR}/${SID}.json"
assert_allows "bad-typed state allows" "${STOP}"
reset
chmod 500 "${DIR}"
assert_allows "unwritable state dir allows (fail open)" "${STOP}"
chmod 700 "${DIR}"

# --- CLI ----------------------------------------------------------------------------------
rm -f "${DIR}"/*
export CLAUDE_CODE_SESSION_ID="sess-cli"
python3 "${CLI}" start --task "refactor X" --criteria "suite green" >/dev/null 2>&1
[ -f "${DIR}/sess-cli.json" ] && pass || failed "cli start writes state"
[ "$(field "${DIR}/sess-cli.json" task)" = "refactor X" ] && pass || failed "cli start records task"
[ "$(field "${DIR}/sess-cli.json" max_iterations)" = "50" ] && pass || failed "cli default max is 50"
[ "$(field "${DIR}/sess-cli.json" iteration)" = "0" ] && pass || failed "cli start iteration 0"
assert_blocks "hook blocks after cli start" '{"session_id":"sess-cli"}'
python3 "${CLI}" status 2>&1 | grep -q "refactor X" && pass || failed "cli status shows task"
python3 "${CLI}" done >/dev/null 2>&1
[ ! -e "${DIR}/sess-cli.json" ] && pass || failed "cli done removes state"
assert_allows "hook allows after cli done" '{"session_id":"sess-cli"}'

python3 "${CLI}" start --task "again" --max 3 >/dev/null 2>&1
[ "$(field "${DIR}/sess-cli.json" max_iterations)" = "3" ] && pass || failed "cli --max honored"
python3 "${CLI}" cancel >/dev/null 2>&1
[ ! -e "${DIR}/sess-cli.json" ] && pass || failed "cli cancel removes state"
[ -e "${DIR}/sess-cli.cancel" ] && pass || failed "cli cancel writes signal"
assert_allows "hook allows after cli cancel" '{"session_id":"sess-cli"}'
python3 "${CLI}" start --task "fresh start" >/dev/null 2>&1
[ ! -e "${DIR}/sess-cli.cancel" ] && pass || failed "cli start clears stale cancel signal"
assert_blocks "restart after cancel blocks again" '{"session_id":"sess-cli"}'

unset CLAUDE_CODE_SESSION_ID
python3 "${CLI}" start --task "no session" >/dev/null 2>&1 && failed "cli without session id must fail" || pass
python3 "${CLI}" --session sess-flag start --task "explicit" >/dev/null 2>&1
[ -f "${DIR}/sess-flag.json" ] && pass || failed "cli --session flag"
python3 "${CLI}" --session "../evil" start --task "x" >/dev/null 2>&1 && failed "cli rejects unsafe session id" || pass
python3 "${CLI}" --session sess-flag start >/dev/null 2>&1 && failed "cli start without task must fail" || pass

echo "persist tests: ${PASS} passed, ${FAIL} failed"
[ "${FAIL}" -eq 0 ]
