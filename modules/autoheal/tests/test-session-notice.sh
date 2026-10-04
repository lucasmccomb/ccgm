#!/usr/bin/env bash
# test-session-notice.sh
#
# hooks/autoheal-session-notice.py (#1099 Phase 3.3): the SessionStart line that
# tells the user about ready fixes and about a dead job.
#
#   1 ready proposal           first session of the day: one line; later sessions: nothing
#   health.json 30h old        stale-run line
#   health status failed       stale-run line
#   health status paused       nothing
#   launchctl program missing  names the missing path (fake launchctl, first on PATH)
#   launchctl program present  nothing
#   cwd under /.claude/worktrees/   nothing, and the day's notice is not used up
#   launchctl absent           the job check is skipped
#
# Every run uses a temp autoheal dir, a temp HOME, and a fake launchctl.
#
# Run: bash modules/autoheal/tests/test-session-notice.sh

set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MODULE_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
HOOK="${MODULE_ROOT}/hooks/autoheal-session-notice.py"

PASS=0
FAIL=0
assert_eq() {
    if [ "$1" = "$2" ]; then
        PASS=$((PASS + 1))
    else
        FAIL=$((FAIL + 1))
        echo "FAIL: $3"
        echo "  expected: $2"
        echo "  actual:   $1"
    fi
}

TMP="$(mktemp -d -t autoheal-notice.XXXXXX)"
trap 'rm -rf "${TMP}"' EXIT

NOW="2026-10-04T12:00:00+00:00"
REAL_PY="$(command -v python3)"

# Fake launchctl: prints $FAKE_LAUNCHCTL_OUT and records each call.
FAKEBIN="${TMP}/fakebin"
mkdir -p "${FAKEBIN}"
cat > "${FAKEBIN}/launchctl" <<'FAKE'
#!/bin/sh
echo "$@" >> "${FAKE_LAUNCHCTL_LOG}"
cat "${FAKE_LAUNCHCTL_OUT}"
FAKE
chmod +x "${FAKEBIN}/launchctl"
# A PATH with python3 and no launchctl at all.
PYONLY="${TMP}/pyonly"
mkdir -p "${PYONLY}"
ln -s "${REAL_PY}" "${PYONLY}/python3"

# scenario <name>: fresh autoheal dir, HOME, LaunchAgents dir with a job plist, good launchctl output.
scenario() {
    S="${TMP}/$1"
    AH="${S}/autoheal"
    FAKE_HOME="${S}/home"
    mkdir -p "${AH}" "${FAKE_HOME}/.claude/autoheal" "${S}/agents"
    : > "${S}/agents/com.tester.ccgm.autoheal.daily.plist"
    : > "${FAKE_HOME}/.claude/autoheal/autoheal-daily.sh"
    LOG="${S}/launchctl.log"
    OUT="${S}/launchctl.out"
    : > "${LOG}"
    launchctl_out "${FAKE_HOME}/.claude/autoheal/autoheal-daily.sh"
}

# launchctl_out <script path>: what `launchctl print` shows for the job.
launchctl_out() {
    cat > "${OUT}" <<EOF
gui/501/com.tester.ccgm.autoheal.daily = {
	state = not running
	program = /bin/sh
	arguments = {
		/bin/sh
		-lc
		$1
	}
}
EOF
}

# ready_row <id> <title>
ready_row() {
    printf '{"id":"%s","signature_id":"%s","state":"ready","kind":"rule_insert","title":"%s","generated_at":"2026-10-04T08:00:00+00:00"}\n' "$1" "$1" "$2" >> "${AH}/proposals.jsonl"
}

# health <status> <generated_at> <last_success_at> [reason message]
health() {
    python3 - "${AH}/health.json" "$1" "$2" "$3" "${4:-}" <<'PY'
import json, sys
path, status, gen, last, msg = sys.argv[1:6]
reasons = [{"code": "x", "message": msg, "fix": "f"}] if msg else []
json.dump({"status": status, "generated_at": gen, "last_success_at": last, "reasons": reasons}, open(path, "w"))
PY
}

# run_hook [cwd] [path override]: stdout of the hook.
run_hook() {
    local cwd="${1:-${S}/project}"
    local path="${2:-${FAKEBIN}:${PATH}}"
    printf '{"hook_event_name":"SessionStart","source":"startup","cwd":"%s"}' "${cwd}" | \
        env PATH="${path}" HOME="${FAKE_HOME}" \
            CCGM_AUTOHEAL_DIR="${AH}" \
            CCGM_AUTOHEAL_NOW="${NOW}" \
            CCGM_AUTOHEAL_REAL_HOME="${FAKE_HOME}" \
            CCGM_AUTOHEAL_LAUNCH_AGENTS_DIR="${S}/agents" \
            FAKE_LAUNCHCTL_LOG="${LOG}" FAKE_LAUNCHCTL_OUT="${OUT}" \
            python3 "${HOOK}" 2>"${S}/stderr"
}

# field <json> <key>: systemMessage, or additionalContext, or "" when absent.
field() {
    printf '%s' "$1" | python3 -c '
import json, sys
raw = sys.stdin.read().strip()
if not raw:
    print(""); sys.exit()
d = json.loads(raw)
if sys.argv[1] == "msg":
    print(d.get("systemMessage", ""))
else:
    print(d.get("hookSpecificOutput", {}).get("additionalContext", ""))
' "$2"
}

# --- 1 ready proposal: first session shows one line, later sessions nothing ---
scenario t1
ready_row sigA "echo zsh_not_found: add a rule to code-quality.md"
out="$(run_hook)"
assert_eq "$(field "${out}" msg)" "autoheal: 1 fix ready (echo zsh_not_found) — run /autoheal-review" "t1: first session of the day shows one line"
assert_eq "$(field "${out}" ctx | grep -c 'autoheal-review')" "1" "t1b: the model gets context naming /autoheal-review"
assert_eq "$(field "${out}" msg | wc -l | tr -d ' ')" "1" "t1c: the user message is one line"
out="$(run_hook)"
assert_eq "${out}" "" "t1d: a later session the same day shows nothing"
assert_eq "$(cat "${S}/stderr")" "" "t1e: nothing on stderr"

# --- two ready proposals, names listed ---------------------------------------
scenario t2
ready_row sigA "echo zsh_not_found: add a rule to code-quality.md"
ready_row sigB "cp interactive_prompt: add a rule to autonomy.md"
assert_eq "$(field "$(run_hook)" msg)" "autoheal: 2 fixes ready (echo zsh_not_found, cp interactive_prompt) — run /autoheal-review" "t2: two ready fixes are named"

# --- only ready rows count --------------------------------------------------
scenario t3
printf '{"id":"a","state":"legacy","title":"old: x"}\n{"id":"b","state":"dropped","title":"d: x"}\n{"id":"c","state":"applied","title":"c: x"}\n{"id":"d","state":"skipped","title":"s: x"}\n' > "${AH}/proposals.jsonl"
assert_eq "$(run_hook)" "" "t3: legacy, dropped, applied and skipped rows say nothing"

# --- health --------------------------------------------------------------
scenario t4
health ok "2026-10-03T06:00:00+00:00" "2026-10-03T06:00:00+00:00"
assert_eq "$(field "$(run_hook)" msg)" "autoheal: last good run 1d ago (no run in the last 26h) — /autoheal doctor" "t4: health.json 30h old shows the stale-run line"

scenario t4b
health failed "2026-10-04T11:00:00+00:00" "2026-10-01T11:00:00+00:00" "analyzer exited 1"
assert_eq "$(field "$(run_hook)" msg)" "autoheal: last good run 3d ago (analyzer exited 1) — /autoheal doctor" "t4b: status failed shows the line with the recorded reason"

scenario t4c
health paused "2026-09-01T00:00:00+00:00" "2026-08-01T00:00:00+00:00"
assert_eq "$(run_hook)" "" "t4c: paused is not a failure"

scenario t4d
health ok "2026-10-04T10:00:00+00:00" "2026-10-04T10:00:00+00:00"
assert_eq "$(run_hook)" "" "t4d: a fresh ok run says nothing"

scenario t4e
assert_eq "$(run_hook)" "" "t4e: no health.json says nothing"

# --- launchd job check ---------------------------------------------------------
scenario t5
launchctl_out "${S}/gone/home/.claude/autoheal/autoheal-daily.sh"
msg="$(field "$(run_hook)" msg)"
assert_eq "${msg}" "autoheal: scheduled job runs ${S}/gone/home/.claude/autoheal/autoheal-daily.sh, which does not exist — /autoheal doctor" "t5: a program path under a missing dir is named"

scenario t5b
assert_eq "$(run_hook)" "" "t5b: a program path that exists says nothing"
assert_eq "$(wc -l < "${LOG}" | tr -d ' ')" "1" "t5c: launchctl print ran once"
assert_eq "$(grep -c 'print gui/' "${LOG}")" "1" "t5d: it ran the print subcommand against the gui domain"
run_hook > /dev/null
assert_eq "$(wc -l < "${LOG}" | tr -d ' ')" "1" "t5e: the second session the same day reads the cache"

scenario t5f
launchctl_out "\$HOME/.claude/autoheal/autoheal-daily.sh"
assert_eq "$(run_hook)" "" "t5f: a literal \$HOME in the arguments resolves against the real home"

scenario t5g
assert_eq "$(run_hook "${S}/project" "${PYONLY}")" "" "t5g: no launchctl on PATH skips the job check"

# --- subagent worktrees stay quiet and keep the day's notice --------------------
scenario t6
ready_row sigA "echo zsh_not_found: add a rule to code-quality.md"
assert_eq "$(run_hook "/Users/x/code/repo/.claude/worktrees/agent-x")" "" "t6: a worktree cwd is silent"
assert_eq "$(field "$(run_hook)" msg)" "autoheal: 1 fix ready (echo zsh_not_found) — run /autoheal-review" "t6b: the next normal session still gets the notice"

# --- autoheal not installed: no output and no files -----------------------------
scenario t7
rm -rf "${AH}"
assert_eq "$(run_hook)" "" "t7: no autoheal dir says nothing"
assert_eq "$([ -e "${AH}" ] && echo created || echo untouched)" "untouched" "t7b: and creates nothing"

# --- a broken ledger or health file never blocks --------------------------------
scenario t8
printf 'not json\n' > "${AH}/proposals.jsonl"
printf '{broken' > "${AH}/health.json"
out="$(run_hook)"
assert_eq "$?" "0" "t8: garbage inputs exit 0"
assert_eq "${out}" "" "t8b: and say nothing"

echo ""
echo "test-session-notice.sh: ${PASS} passed, ${FAIL} failed"
[ "${FAIL}" -eq 0 ]
