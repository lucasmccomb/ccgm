#!/usr/bin/env bash
# Tests for ask-context-gate.py — the hard PreToolUse gate that blocks
# AskUserQuestion calls whose decision context is invisible to the user.
#
# Exit-code contract under test: 2 = hard block, 0 = allowed.
#
# Run: bash modules/ask-context/tests/test-ask-context-gate.sh

set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MODULE_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
HOOK="${MODULE_ROOT}/hooks/ask-context-gate.py"

PASS=0
FAIL=0

# A clean slate: an inherited escape hatch would flip every deny-case to allow.
unset CCGM_ASK_CONTEXT_OFF
unset ASK_CONTEXT_MIN_CHARS

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
    if printf '%s' "${haystack}" | grep -qF -- "${needle}"; then
        PASS=$((PASS + 1))
    else
        FAIL=$((FAIL + 1))
        echo "FAIL: ${label}"
        echo "  missing: ${needle}"
        echo "  in:      ${haystack}"
    fi
}

TMP=$(mktemp -d -t ask-context.XXXXXX)
trap 'python3 -c "import shutil,sys; shutil.rmtree(sys.argv[1], ignore_errors=True)" "${TMP}"' EXIT

# ─── Fixtures: payloads + transcripts, generated in one deterministic pass ───
python3 - "${TMP}" <<'PYEOF'
import json, sys, os
tmp = sys.argv[1]

def w(name, obj):
    with open(os.path.join(tmp, name), "w") as fh:
        json.dump(obj, fh)

def wt(name, entries):
    with open(os.path.join(tmp, name), "w") as fh:
        for e in entries:
            fh.write(json.dumps(e) + "\n")

SELF_Q = ("Should PR 123 land before or after today's release? It fixes device "
          "rebinding but its picker bugs ship in every current build.")
SELF = {"questions": [{
    "question": SELF_Q,
    "header": "PR 123",
    "multiSelect": False,
    "options": [
        {"label": "Land after release",
         "description": "Cut the release from tested main; merge PR 123 right after."},
        {"label": "Land before release",
         "description": "Rebase and re-verify now; it joins this release."},
    ],
}]}
DEICTIC = {"questions": [{
    "question": "With that context: disposition for PR 123?",
    "header": "PR 123",
    "multiSelect": False,
    "options": [
        {"label": "Land after release", "description": "Ship it after."},
        {"label": "Land before release", "description": "Ship it before."},
    ],
}]}
DEICTIC_DESC = {"questions": [{
    "question": "Should PR 123 land before or after today's release?",
    "header": "PR 123",
    "multiSelect": False,
    "options": [
        {"label": "Land after release", "description": "As described above, it rides the next release."},
        {"label": "Land before release", "description": "It joins this release."},
    ],
}]}
w("self.json", SELF)
w("deictic.json", DEICTIC)
w("deictic_desc.json", DEICTIC_DESC)

user_msg = {"type": "user", "message": {"role": "user", "content": "pick a disposition for PR 123"}}
def a_text(text):
    return {"type": "assistant", "message": {"content": [{"type": "text", "text": text}]}}
def a_think(t="deep analysis the user never sees " * 20):
    return {"type": "assistant", "message": {"content": [{"type": "thinking", "thinking": t}]}}
def a_tool(tid, name="Bash", tin=None):
    return {"type": "assistant", "message": {"content": [
        {"type": "tool_use", "id": tid, "name": name, "input": tin or {"command": "git log --oneline"}}]}}
def a_ask(tid, payload):
    return {"type": "assistant", "message": {"content": [
        {"type": "tool_use", "id": tid, "name": "AskUserQuestion", "input": payload}]}}
def t_result(tid, text):
    return {"type": "user", "message": {"content": [
        {"type": "tool_result", "tool_use_id": tid, "content": text}]}}

brief = a_text("Context brief: PR 123 fixes device rebinding. Its picker bugs ship "
               "in every current build. Landing before the release means a rebase and "
               "re-verify now; landing after means the fix rides the next release. "
               "Evidence: the release branch was cut from tested main this morning.")

# First action after a user message — no prior tools, current call not yet flushed.
wt("t_first_action.jsonl", [user_msg, a_think()])
# Current call already flushed as the ONLY tool_use — self-exclusion must yield 0 prior tools.
wt("t_self_excluded.jsonl", [user_msg, a_think(), a_ask("tu_cur", SELF)])
# Mid-workstream, zero visible text: thinking + a Bash call + its result, ask flushed.
wt("t_midturn_dark.jsonl", [user_msg, a_think(), a_tool("tu_1"),
                            t_result("tu_1", "abc123 fix picker"), a_ask("tu_cur", SELF)])
# Same, but a visible brief was emitted before asking.
wt("t_midturn_brief.jsonl", [user_msg, a_think(), a_tool("tu_1"),
                             t_result("tu_1", "abc123 fix picker"), brief, a_ask("tu_cur", SELF)])
# Sidechain text must NOT count as visible context.
side = dict(a_text("x" * 1000)); side["isSidechain"] = True
wt("t_sidechain.jsonl", [user_msg, side, a_tool("tu_1"),
                         t_result("tu_1", "abc123"), a_ask("tu_cur", SELF)])

answered_free = ('Your questions have been answered: "' + SELF_Q +
                 '"="you didn\'t give me any context." You can now continue.')
answered_opt = ('Your questions have been answered: "' + SELF_Q +
                '"="Land after release". You can now continue.')
rejected = ("The user doesn't want to proceed with this tool use. The tool use was "
            "rejected. To tell you how to proceed, the user said:\ngive me context first")

# Prior identical ask answered with FREE TEXT, then identical re-ask flushed.
wt("t_repeat_free.jsonl", [user_msg, brief, a_ask("tu_a", SELF),
                           t_result("tu_a", answered_free), brief, a_ask("tu_cur", SELF)])
# Prior identical ask answered by PICKING AN OFFERED OPTION — re-ask allowed.
wt("t_repeat_opt.jsonl", [user_msg, brief, a_ask("tu_a", SELF),
                          t_result("tu_a", answered_opt), brief, a_ask("tu_cur", SELF)])
# Prior identical ask REJECTED.
wt("t_repeat_rejected.jsonl", [user_msg, brief, a_ask("tu_a", SELF),
                               t_result("tu_a", rejected), brief, a_ask("tu_cur", SELF)])
# Prior identical ask never answered (interrupted).
wt("t_repeat_interrupted.jsonl", [user_msg, brief, a_ask("tu_a", SELF),
                                  brief, a_ask("tu_cur", SELF)])

# Malformed lines interleaved — parser must skip them and still gate (G3:
# a tool call happened, no visible text was emitted).
with open(os.path.join(tmp, "t_malformed.jsonl"), "w") as fh:
    fh.write("not json at all\n")
    fh.write(json.dumps(user_msg) + "\n")
    fh.write("{truncated\n")
    fh.write(json.dumps(a_tool("tu_1")) + "\n")
    fh.write(json.dumps(t_result("tu_1", "ok")) + "\n")
PYEOF

# run_hook TOOL PAYLOAD_FILE TRANSCRIPT_PATH
# Feeds the hook a PreToolUse envelope on stdin. Stderr lands in $HOOK_STDERR.
HOOK_STDERR=""
run_hook() {
    local tool="$1" payload_file="$2" transcript="$3"
    local errfile="${TMP}/stderr.txt"
    python3 - "$tool" "$payload_file" "$transcript" <<'PYEOF' | python3 "${HOOK}" 2>"${errfile}"
import json, sys
tool, payload_file, transcript = sys.argv[1:4]
tin = json.load(open(payload_file)) if payload_file != "-" else {}
sys.stdout.write(json.dumps({
    "session_id": "test",
    "tool_name": tool,
    "tool_input": tin,
    "transcript_path": transcript,
    "permission_mode": "default",
    "cwd": "/tmp",
}))
PYEOF
    local rc=$?
    HOOK_STDERR="$(cat "${errfile}" 2>/dev/null || true)"
    return $rc
}

# ─── Cases ───────────────────────────────────────────────────────────────────

run_hook "Bash" "${TMP}/self.json" "${TMP}/t_first_action.jsonl"
assert_eq "$?" "0" "other tools are never gated"

run_hook "AskUserQuestion" "${TMP}/deictic.json" "/nonexistent"
assert_eq "$?" "2" "G1: deictic question text blocks (payload-only, no transcript needed)"
assert_contains "${HOOK_STDERR}" "cannot see" "G1 block message names the visibility problem"
assert_contains "${HOOK_STDERR}" "With that context" "G1 block message quotes the matched phrase"

run_hook "AskUserQuestion" "${TMP}/deictic_desc.json" "/nonexistent"
assert_eq "$?" "2" "G1: deictic option description blocks"

run_hook "AskUserQuestion" "${TMP}/self.json" "${TMP}/t_first_action.jsonl"
assert_eq "$?" "0" "first action after a user message is exempt (their message is the context)"

run_hook "AskUserQuestion" "${TMP}/self.json" "${TMP}/t_self_excluded.jsonl"
assert_eq "$?" "0" "the in-flight call's own flushed tool_use is excluded from both gates"

run_hook "AskUserQuestion" "${TMP}/self.json" "${TMP}/t_midturn_dark.jsonl"
assert_eq "$?" "2" "G3: mid-workstream with zero visible text blocks"
assert_contains "${HOOK_STDERR}" "mid-workstream" "G3 block message states the condition"

run_hook "AskUserQuestion" "${TMP}/self.json" "${TMP}/t_midturn_brief.jsonl"
assert_eq "$?" "0" "G3: a visible context brief before asking passes"

run_hook "AskUserQuestion" "${TMP}/self.json" "${TMP}/t_sidechain.jsonl"
assert_eq "$?" "2" "G3: sidechain (subagent) text does not count as visible context"

run_hook "AskUserQuestion" "${TMP}/self.json" "${TMP}/t_repeat_free.jsonl"
assert_eq "$?" "2" "G2: identical re-ask after a free-text (Other) answer blocks"
assert_contains "${HOOK_STDERR}" "already asked" "G2 block message names the repeat"

run_hook "AskUserQuestion" "${TMP}/self.json" "${TMP}/t_repeat_opt.jsonl"
assert_eq "$?" "0" "G2: identical re-ask after an offered-option answer is allowed (loops)"

run_hook "AskUserQuestion" "${TMP}/self.json" "${TMP}/t_repeat_rejected.jsonl"
assert_eq "$?" "2" "G2: identical re-ask after a rejection blocks"

run_hook "AskUserQuestion" "${TMP}/self.json" "${TMP}/t_repeat_interrupted.jsonl"
assert_eq "$?" "2" "G2: identical re-ask after an interrupted ask blocks"

CCGM_ASK_CONTEXT_OFF=1 run_hook "AskUserQuestion" "${TMP}/deictic.json" "/nonexistent"
assert_eq "$?" "0" "CCGM_ASK_CONTEXT_OFF=1 escape hatch bypasses every gate"

run_hook "AskUserQuestion" "${TMP}/self.json" "/nonexistent"
assert_eq "$?" "0" "missing transcript fails open for the transcript gates"

run_hook "AskUserQuestion" "${TMP}/self.json" "${TMP}/t_malformed.jsonl"
assert_eq "$?" "2" "malformed transcript lines are skipped, valid entries still gate (G3)"

ASK_CONTEXT_MIN_CHARS=1000 run_hook "AskUserQuestion" "${TMP}/self.json" "${TMP}/t_midturn_brief.jsonl"
assert_eq "$?" "2" "ASK_CONTEXT_MIN_CHARS overrides the G3 threshold (raised past the brief)"

# ─── Summary ─────────────────────────────────────────────────────────────────
echo ""
echo "ask-context-gate: ${PASS} passed, ${FAIL} failed"
[ "${FAIL}" -eq 0 ] || exit 1
exit 0
