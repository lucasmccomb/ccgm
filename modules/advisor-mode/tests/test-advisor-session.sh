#!/usr/bin/env bash
# Tests for advisor mode's PER-SESSION state: the flag is
# ~/.claude/advisor-mode/<session_id>, so one session's mode never binds
# another's. Covers session isolation in both hooks, session-id resolution
# (stdin, environment fallback, fail-open when there is neither), the
# SessionStart auto-on and its opt-out, the compaction exception, legacy
# migration, SessionEnd removal, and garbage collection.
#
# The guard's own allowlists are covered by test-advisor-guard.sh.
#
# Run: bash modules/advisor-mode/tests/test-advisor-session.sh

set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MODULE_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
GUARD="${MODULE_ROOT}/hooks/advisor-guard.py"
POSTURE="${MODULE_ROOT}/hooks/advisor-posture.py"
START="${MODULE_ROOT}/hooks/advisor-session-start.py"
END="${MODULE_ROOT}/hooks/advisor-session-end.py"

PASS=0
FAIL=0

# A leaked hatch or a real session id in the environment would rewrite every
# expectation below.
unset ADVISOR_DIRECT
unset CLAUDE_CODE_SESSION_ID
unset CCGM_ADVISOR_AUTO

pass() { PASS=$((PASS + 1)); }

failed() {
    FAIL=$((FAIL + 1))
    echo "FAIL: $1"
    if [ -n "${2:-}" ]; then echo "  $2"; fi
}

assert_exit() {
    local expected="$1" label="$2" input="$3" actual
    printf '%s' "${input}" | python3 "${GUARD}" >/dev/null 2>&1
    actual=$?
    if [ "${actual}" = "${expected}" ]; then
        pass
    else
        failed "${label}" "expected exit ${expected}, got ${actual}"
    fi
}

assert_file() {
    if [ -f "$2" ]; then pass; else failed "$1" "missing file: $2"; fi
}

assert_no_file() {
    if [ -f "$2" ]; then failed "$1" "unexpected file: $2"; else pass; fi
}

assert_contains() {
    # $1 label, $2 haystack, $3 needle
    if printf '%s' "$2" | grep -qF "$3"; then
        pass
    else
        failed "$1" "expected to contain '$3', got: $2"
    fi
}

assert_empty() {
    if [ -z "$2" ]; then pass; else failed "$1" "expected no output, got: $2"; fi
}

TMP=$(mktemp -d -t advisor-session.XXXXXX)
export HOME="${TMP}/home"
DIR="${HOME}/.claude/advisor-mode"
PROJECTS="${HOME}/.claude/projects/proj"
ENV_FILE="${HOME}/.claude/.ccgm.env"
REPO_FILE="${HOME}/code/repo/src/app.py"
mkdir -p "${HOME}/.claude" "${PROJECTS}" "${HOME}/code/repo/src"

SID_A=session-aaa
SID_B=session-bbb
SID_C=session-ccc

edit_json() {
    # $1 session id (omit for an input that carries none)
    if [ -z "${1:-}" ]; then
        printf '{"tool_name":"Edit","tool_input":{"file_path":"%s"}}' "${REPO_FILE}"
    else
        printf '{"tool_name":"Edit","tool_input":{"file_path":"%s"},"session_id":"%s"}' \
            "${REPO_FILE}" "$1"
    fi
}

edit_json_field() {
    # $1 session id, always emitted as a field (even when empty)
    printf '{"tool_name":"Edit","tool_input":{"file_path":"%s"},"session_id":"%s"}' \
        "${REPO_FILE}" "$1"
}

start_hook() {
    # $1 session id, $2 source
    printf '{"session_id":"%s","source":"%s"}' "$1" "$2" \
        | python3 "${START}" >/dev/null 2>&1
}

end_hook() {
    printf '{"session_id":"%s","reason":"exit"}' "$1" \
        | python3 "${END}" >/dev/null 2>&1
}

posture_out() {
    printf '{"session_id":"%s"}' "$1" | python3 "${POSTURE}" 2>/dev/null
}

age() {
    # $1 path, $2 seconds into the past. python3 rather than `touch -t`/-d:
    # the two spellings differ between BSD and GNU, this one is portable.
    python3 -c 'import os, sys, time
t = time.time() - float(sys.argv[2])
os.utime(sys.argv[1], (t, t))' "$1" "$2"
}

reset_state() {
    # rmtree refuses a symlink, so unlink one first: without this a failing
    # symlink case would poison every later case instead of failing alone.
    if [ -L "${DIR}" ]; then rm -f "${DIR}"; fi
    python3 -c 'import shutil, sys; shutil.rmtree(sys.argv[1], ignore_errors=True)' "${DIR}"
    rm -f "${ENV_FILE}"
    rm -f "${PROJECTS}"/*.jsonl 2>/dev/null
}

# ─── Per-session isolation ───────────────────────────────────────────────────

reset_state
mkdir -p "${DIR}"
printf 'on 2026-01-01T00:00:00Z\n' > "${DIR}/${SID_A}"

assert_exit 2 "session A is on: Edit denied" "$(edit_json "${SID_A}")"
assert_exit 0 "session B is off: the same Edit is allowed" "$(edit_json "${SID_B}")"

out_a=$(posture_out "${SID_A}")
assert_contains "posture injects for session A" "${out_a}" "hookSpecificOutput"
assert_contains "posture names session A's id" "${out_a}" "${SID_A}"
assert_empty "posture is silent for session B" "$(posture_out "${SID_B}")"

# ─── Session-id resolution ───────────────────────────────────────────────────

assert_exit 0 "no session id anywhere: fails open" "$(edit_json '')"
CLAUDE_CODE_SESSION_ID="${SID_A}" \
    assert_exit 2 "env fallback resolves the session: Edit denied" "$(edit_json '')"
CLAUDE_CODE_SESSION_ID="${SID_B}" \
    assert_exit 0 "env fallback for an off session: Edit allowed" "$(edit_json '')"
# Session A is on and B is off, so exit 2 is reachable only if stdin wins.
CLAUDE_CODE_SESSION_ID="${SID_B}" \
    assert_exit 2 "stdin wins over the environment" "$(edit_json "${SID_A}")"

# ─── SessionStart: auto-on, and the compaction exception ─────────────────────

for src in startup resume clear; do
    reset_state
    start_hook "${SID_A}" "${src}"
    assert_file "SessionStart(${src}) creates the flag" "${DIR}/${SID_A}"
done

reset_state
start_hook "${SID_A}" compact
assert_no_file "SessionStart(compact) does not create the flag" "${DIR}/${SID_A}"

reset_state
start_hook "" startup
assert_empty "SessionStart with no session id creates no flag" "$(ls -A "${DIR}")"

# An existing flag keeps its original timestamp across a resume.
reset_state
mkdir -p "${DIR}"
printf 'on 2020-01-01T00:00:00Z\n' > "${DIR}/${SID_A}"
start_hook "${SID_A}" resume
assert_contains "SessionStart does not rewrite an existing flag" \
    "$(cat "${DIR}/${SID_A}")" "2020-01-01T00:00:00Z"

# ─── The CCGM_ADVISOR_AUTO opt-out ───────────────────────────────────────────

reset_state
CCGM_ADVISOR_AUTO=false start_hook "${SID_A}" startup
assert_no_file "CCGM_ADVISOR_AUTO=false in the environment opts out" "${DIR}/${SID_A}"

reset_state
CCGM_ADVISOR_AUTO=true start_hook "${SID_A}" startup
assert_file "CCGM_ADVISOR_AUTO=true in the environment stays on" "${DIR}/${SID_A}"

reset_state
printf 'CCGM_ADVISOR_AUTO=false\n' > "${ENV_FILE}"
start_hook "${SID_A}" startup
assert_no_file "CCGM_ADVISOR_AUTO=false in .ccgm.env opts out" "${DIR}/${SID_A}"

reset_state
printf 'CCGM_ADVISOR_AUTO=true\n' > "${ENV_FILE}"
start_hook "${SID_A}" startup
assert_file "CCGM_ADVISOR_AUTO=true in .ccgm.env stays on" "${DIR}/${SID_A}"

reset_state
printf 'CCGM_ADVISOR_AUTO=false\n' > "${ENV_FILE}"
CCGM_ADVISOR_AUTO=true start_hook "${SID_A}" startup
assert_file "the environment wins over .ccgm.env" "${DIR}/${SID_A}"

# A .ccgm.env line the operator meant as "off" must never be read as "on":
# this is an opt-OUT flag, so a misparse silently overrides them.
opt_out_case() {
    # $1 label, $2 .ccgm.env content
    reset_state
    printf '%b' "$2" > "${ENV_FILE}"
    start_hook "${SID_A}" startup
    assert_no_file "$1" "${DIR}/${SID_A}"
}

opt_out_case "export prefix opts out" 'export CCGM_ADVISOR_AUTO=false\n'
opt_out_case "trailing comment opts out" 'CCGM_ADVISOR_AUTO=false  # off please\n'
opt_out_case "spaces around = opt out" 'CCGM_ADVISOR_AUTO = false\n'
opt_out_case "quoted value opts out" 'CCGM_ADVISOR_AUTO="false"\n'
opt_out_case "uppercase value opts out" 'CCGM_ADVISOR_AUTO=FALSE\n'
opt_out_case "the last matching line wins" \
    'CCGM_ADVISOR_AUTO=true\nCCGM_ADVISOR_AUTO=false\n'

reset_state
printf 'CCGM_ADVISOR_AUTO=false\nCCGM_ADVISOR_AUTO=true\n' > "${ENV_FILE}"
start_hook "${SID_A}" startup
assert_file "the last matching line wins the other way too" "${DIR}/${SID_A}"

reset_state
printf '# CCGM_ADVISOR_AUTO=false\n' > "${ENV_FILE}"
start_hook "${SID_A}" startup
assert_file "a commented-out line is not an opt-out" "${DIR}/${SID_A}"

reset_state
start_hook "${SID_A}" startup
assert_file "unset means on" "${DIR}/${SID_A}"

# Garbage collection still runs while the auto-on is opted out.
reset_state
mkdir -p "${DIR}"
touch "${DIR}/${SID_B}"
age "${DIR}/${SID_B}" 7200
CCGM_ADVISOR_AUTO=false start_hook "${SID_A}" startup
assert_no_file "GC runs even when opted out" "${DIR}/${SID_B}"
assert_no_file "opted out: no flag for this session either" "${DIR}/${SID_A}"

# ─── Legacy migration: the state path used to be a regular file ──────────────

reset_state
printf 'on 2026-01-01T00:00:00Z\n' > "${DIR}"
start_hook "${SID_A}" startup
if [ -d "${DIR}" ]; then pass; else failed "legacy file becomes the state directory"; fi
assert_file "the migrated session gets its own flag" "${DIR}/${SID_A}"

# A symlink standing where the directory belongs is the same dead end as the
# legacy file: without migration, makedirs, listdir and the flag write all
# fail and every session runs un-gated.
reset_state
printf 'on 2026-01-01T00:00:00Z\n' > "${HOME}/.claude/legacy-target"
ln -s "${HOME}/.claude/legacy-target" "${DIR}"
start_hook "${SID_A}" startup
if [ -d "${DIR}" ] && [ ! -L "${DIR}" ]; then
    pass
else
    failed "a symlink at the state path becomes a real directory"
fi
assert_file "the symlink's target is left alone" "${HOME}/.claude/legacy-target"
assert_file "the session gets its flag after the symlink is cleared" "${DIR}/${SID_A}"
assert_exit 2 "the mode is actually on after the symlink is cleared" \
    "$(edit_json "${SID_A}")"
rm -f "${HOME}/.claude/legacy-target"

# ─── Session ids that must never name a file outside the state directory ─────

# All four hooks inline the same SESSION_ID_RE; this keeps the copies honest.
reset_state
mkdir -p "${DIR}"
HOME_BEFORE=$(find "${HOME}" | sort)
for bad in "../escaped" ".." "." "a/b" "/etc/passwd" "sub/../../out" "" "   "; do
    start_hook "${bad}" startup
    end_hook "${bad}"
    posture_bad=$(posture_out "${bad}")
    assert_empty "posture stays silent for session id '${bad}'" "${posture_bad}"
    assert_exit 0 "guard fails open for session id '${bad}'" \
        "$(edit_json_field "${bad}")"
done
if [ "${HOME_BEFORE}" = "$(find "${HOME}" | sort)" ]; then
    pass
else
    failed "a rejected session id created or removed a path" \
        "now: $(find "${HOME}" | sort | tr '\n' ' ')"
fi

start_hook "ok-normal-id" startup
assert_file "a normal session id creates exactly its own flag" "${DIR}/ok-normal-id"
assert_empty "and nothing else in the state directory" \
    "$(ls -A "${DIR}" | grep -v '^ok-normal-id$')"
assert_exit 2 "and the guard binds that session" "$(edit_json_field "ok-normal-id")"

# ─── SessionEnd removes only this session's flag ─────────────────────────────

reset_state
mkdir -p "${DIR}"
touch "${DIR}/${SID_A}" "${DIR}/${SID_B}"
end_hook "${SID_A}"
assert_no_file "SessionEnd removes this session's flag" "${DIR}/${SID_A}"
assert_file "SessionEnd leaves other sessions alone" "${DIR}/${SID_B}"

# ─── Garbage collection ──────────────────────────────────────────────────────

# No transcript: swept only after the grace period, so a session that started
# seconds ago and has not written its transcript yet is never swept.
reset_state
mkdir -p "${DIR}"
touch "${DIR}/${SID_B}" "${DIR}/${SID_C}"
age "${DIR}/${SID_B}" 7200
start_hook "${SID_A}" startup
assert_no_file "GC drops a transcript-less flag older than the grace period" "${DIR}/${SID_B}"
assert_file "GC keeps a fresh transcript-less flag" "${DIR}/${SID_C}"

# With a transcript, the transcript's own mtime decides.
reset_state
mkdir -p "${DIR}"
touch "${DIR}/${SID_B}" "${DIR}/${SID_C}"
touch "${PROJECTS}/${SID_B}.jsonl" "${PROJECTS}/${SID_C}.jsonl"
age "${DIR}/${SID_B}" 7200
age "${DIR}/${SID_C}" 7200
age "${PROJECTS}/${SID_B}.jsonl" 345600   # 4 days
start_hook "${SID_A}" startup
assert_no_file "GC drops a flag whose transcript is days stale" "${DIR}/${SID_B}"
assert_file "GC keeps a flag whose transcript is fresh" "${DIR}/${SID_C}"

# The current session is never swept, however old its flag is. Opted out on
# purpose: with the auto-on running, enable() re-creates whatever GC just
# removed, and assert_file cannot tell "never deleted" from "deleted and
# re-created". The content assertion pins the same thing a second way.
reset_state
mkdir -p "${DIR}"
printf 'on 2020-01-01T00:00:00Z\n' > "${DIR}/${SID_A}"
age "${DIR}/${SID_A}" 7200
CCGM_ADVISOR_AUTO=false start_hook "${SID_A}" startup
assert_file "GC never removes the current session's flag" "${DIR}/${SID_A}"
assert_contains "the current session's flag is not rewritten either" \
    "$(cat "${DIR}/${SID_A}" 2>/dev/null)" "2020-01-01T00:00:00Z"

# ─── Summary ─────────────────────────────────────────────────────────────────

python3 -c "import shutil; shutil.rmtree('${TMP}', ignore_errors=True)"
echo ""
echo "advisor-session tests: ${PASS} passed, ${FAIL} failed"
[ "${FAIL}" = "0" ] || exit 1
