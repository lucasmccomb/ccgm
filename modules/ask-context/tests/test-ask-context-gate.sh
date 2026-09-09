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
# Rich payload: the question plus consequence-bearing descriptions carry the
# context on their own (>= 200 chars across question + descriptions).
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
# Thin payload: same self-contained question, one-line descriptions (< 200).
THIN = {"questions": [{
    "question": SELF_Q,
    "header": "PR 123",
    "multiSelect": False,
    "options": [
        {"label": "Land after release", "description": "Ship it after."},
        {"label": "Land before release", "description": "Ship it before."},
    ],
}]}
# Bare payload: no context at all in any field.
BARE = {"questions": [{
    "question": "Which option?",
    "header": "Pick",
    "multiSelect": False,
    "options": [
        {"label": "A", "description": "A"},
        {"label": "B", "description": "B"},
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

def payload_chars(p):
    total = 0
    for q in p["questions"]:
        total += len(q["question"].strip())
        for o in q["options"]:
            total += len(o.get("description", "").strip()) + len(o.get("preview", "").strip())
    return total

# The G3 cases below key on which side of the 200-char default each payload
# falls; pin that here so a wording tweak cannot silently flip a case.
assert payload_chars(SELF) >= 200, payload_chars(SELF)
assert payload_chars(THIN) < 200, payload_chars(THIN)
assert payload_chars(BARE) < 200, payload_chars(BARE)

w("self.json", SELF)
w("thin.json", THIN)
w("bare.json", BARE)
w("deictic.json", DEICTIC)
w("deictic_desc.json", DEICTIC_DESC)

user_msg = {"type": "user", "message": {"role": "user", "content": "pick a disposition for PR 123"}}
def u_str(text):
    return {"type": "user", "message": {"role": "user", "content": text}}
def u_meta(text):
    return {"type": "user", "isMeta": True,
            "message": {"role": "user", "content": [{"type": "text", "text": text}]}}
def a_text(text):
    return {"type": "assistant", "message": {"content": [{"type": "text", "text": text}]}}
def a_think(t="deep analysis the user never sees " * 20):
    return {"type": "assistant", "message": {"content": [
        {"type": "thinking", "thinking": t, "signature": "sig"}]}}
def a_tool(tid, name="Bash", tin=None):
    return {"type": "assistant", "message": {"content": [
        {"type": "tool_use", "id": tid, "name": name, "input": tin or {"command": "git log --oneline"}}]}}
def a_ask(tid, payload):
    return {"type": "assistant", "message": {"content": [
        {"type": "tool_use", "id": tid, "name": "AskUserQuestion", "input": payload}]}}
def t_result(tid, text):
    return {"type": "user", "message": {"content": [
        {"type": "tool_result", "tool_use_id": tid, "content": text}]}}

BRIEF_TEXT = ("Context brief: PR 123 fixes device rebinding. Its picker bugs ship "
              "in every current build. Landing before the release means a rebase and "
              "re-verify now; landing after means the fix rides the next release. "
              "Evidence: the release branch was cut from tested main this morning.")
assert len(BRIEF_TEXT) >= 200
brief = a_text(BRIEF_TEXT)

# First action after a user message — no prior tools, current call not yet flushed.
wt("t_first_action.jsonl", [user_msg, a_think()])
# Current call already flushed as the ONLY tool_use — self-exclusion must yield 0 prior tools.
wt("t_self_excluded.jsonl", [user_msg, a_think(), a_ask("tu_cur", SELF)])
# Mid-workstream, zero visible text, thin payload: thinking + a Bash call + its result, ask flushed.
wt("t_midturn_dark.jsonl", [user_msg, a_think(), a_tool("tu_1"),
                            t_result("tu_1", "abc123 fix picker"), a_ask("tu_cur", THIN)])
# Same, but a visible brief was emitted before asking.
wt("t_midturn_brief.jsonl", [user_msg, a_think(), a_tool("tu_1"),
                             t_result("tu_1", "abc123 fix picker"), brief, a_ask("tu_cur", THIN)])
# Same dark transcript, but the payload itself carries the context.
wt("t_payload_dark.jsonl", [user_msg, a_think(), a_tool("tu_1"),
                            t_result("tu_1", "abc123 fix picker"), a_ask("tu_cur", SELF)])
# Sidechain text must NOT count as visible context.
side = dict(a_text("x" * 1000)); side["isSidechain"] = True
wt("t_sidechain.jsonl", [user_msg, side, a_tool("tu_1"),
                         t_result("tu_1", "abc123"), a_ask("tu_cur", THIN)])

# ── The reported failure (Claude Code 2.1.267 + Claude Fable 5.1, 2026-09-09).
# Shape observed in the session transcript: the harness appends the skill
# expansion as an isMeta user entry; each turn-opening text block is stored
# verbatim; the brief written between tool calls right before the ask is
# stored as a progress-update `thinking` block (a one-line summary), never as
# `text`. The old gate started the turn at the injected entry and counted 86
# chars; the fix starts it at the human's message and lets the payload pass.
OPEN_1 = "I'll start the autonomous xplan flow for this system design interview prep feature."
OPEN_2 = "I'll read the main xplan command file to execute its full workflow in autonomous mode."
with open(os.path.join(tmp, "fable_text_chars.txt"), "w") as fh:
    fh.write(str(len(OPEN_1) + len(OPEN_2)))
expansion = u_meta("# xplana - Autonomous xplan\n\n" + ("Runs the full xplan pipeline end-to-end. " * 220))
summary_update = a_think(
    "Before starting research, I need you to pick how many adversarial review passes "
    "the finished plan should get in Phase 5.7 — more passes take longer but catch more "
    "issues before execution. This is the only question I'll ask; everything else runs "
    "unattended until the final execution gate.")
def fable(payload):
    return [
        u_str("I need a full system design interview prep plan; run the whole flow autonomously."),
        a_think(""), a_text(OPEN_1),
        a_tool("tu_skill", "Skill", {"skill": "xplana"}), t_result("tu_skill", "Launching skill: xplana"),
        expansion,
        a_think(""), a_text(OPEN_2),
        a_tool("tu_1", "Bash", {"command": "sed -n 1,80p xplan.md"}), t_result("tu_1", "# xplan ..."),
        a_tool("tu_2", "Read", {"file_path": "/repo/README.md"}), t_result("tu_2", "# repo"),
        a_think(""), summary_update,
        a_ask("tu_cur", payload),
    ]
wt("t_fable_rich.jsonl", fable(SELF))
wt("t_fable_bare.jsonl", fable(BARE))

# Harness-injected user entries do not start a turn: the brief that opened the
# turn still counts even though several injected entries follow it.
wt("t_injected_skip.jsonl", [
    user_msg, brief,
    a_tool("tu_skill", "Skill", {"skill": "xplana"}), t_result("tu_skill", "Launching skill: xplana"),
    expansion,
    u_str("<system-reminder>\nAs you answer the user's questions, you can use the following context:\n# gitStatus\nclean\n</system-reminder>"),
    u_str("<local-command-caveat>Caveat: The messages below were generated by the user while running local commands.</local-command-caveat>"),
    u_str("<local-command-stdout>ok</local-command-stdout>"),
    u_str("[Image: source: /tmp/cache/1.png]"),
    a_tool("tu_1"), t_result("tu_1", "abc123"), a_ask("tu_cur", BARE)])

# Over-skipping guard: a real message that merely carries an appended reminder
# block is still a turn boundary, so the previous turn's brief must not count.
earlier = [u_str("earlier request"), brief, a_tool("tu_0"), t_result("tu_0", "ok")]
real_with_reminder = {"type": "user", "message": {"role": "user", "content": [
    {"type": "text", "text": "pick a disposition for PR 123"},
    {"type": "text", "text": "<system-reminder>\ngitStatus: clean\n</system-reminder>"}]}}
wt("t_reminder_in_real.jsonl", earlier + [real_with_reminder, a_think(), a_tool("tu_1"),
                                         t_result("tu_1", "abc123"), a_ask("tu_cur", BARE)])
# A typed slash command is a human action and therefore a boundary too.
wt("t_command_boundary.jsonl", earlier + [
    u_str("<command-name>/model</command-name>\n<command-message>model</command-message>\n<command-args></command-args>"),
    u_str("<local-command-stdout>Set model to Opus</local-command-stdout>"),
    a_tool("tu_1"), t_result("tu_1", "abc123"), a_ask("tu_cur", BARE)])

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
# a tool call happened, no visible text, thin payload).
with open(os.path.join(tmp, "t_malformed.jsonl"), "w") as fh:
    fh.write("not json at all\n")
    fh.write(json.dumps(user_msg) + "\n")
    fh.write("{truncated\n")
    fh.write(json.dumps(a_tool("tu_1")) + "\n")
    fh.write(json.dumps(t_result("tu_1", "ok")) + "\n")
PYEOF
if [ $? -ne 0 ]; then
    echo "FAIL: fixture generation failed"
    exit 1
fi

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

run_hook "AskUserQuestion" "${TMP}/thin.json" "${TMP}/t_midturn_dark.jsonl"
assert_eq "$?" "2" "G3: mid-workstream, zero visible text, thin payload blocks"
assert_contains "${HOOK_STDERR}" "mid-workstream" "G3 block message states the condition"
assert_contains "${HOOK_STDERR}" "IN THE PAYLOAD" "G3 block message teaches the payload recipe"

run_hook "AskUserQuestion" "${TMP}/thin.json" "${TMP}/t_midturn_brief.jsonl"
assert_eq "$?" "0" "G3: a visible text brief before asking passes (transcript surface)"

run_hook "AskUserQuestion" "${TMP}/self.json" "${TMP}/t_payload_dark.jsonl"
assert_eq "$?" "0" "G3: a payload that carries the context passes with zero visible text (payload surface)"

run_hook "AskUserQuestion" "${TMP}/thin.json" "${TMP}/t_sidechain.jsonl"
assert_eq "$?" "2" "G3: sidechain (subagent) text does not count as visible context"

# The reported failure: turn-opening text stored verbatim, the pre-ask brief
# present only as a summarized thinking block, skill expansion injected.
run_hook "AskUserQuestion" "${TMP}/self.json" "${TMP}/t_fable_rich.jsonl"
assert_eq "$?" "0" "G3: evidence-shaped transcript + context-bearing payload passes (the reported false block)"

run_hook "AskUserQuestion" "${TMP}/bare.json" "${TMP}/t_fable_bare.jsonl"
assert_eq "$?" "2" "G3: evidence-shaped transcript + bare payload still blocks (regression guard)"
assert_contains "${HOOK_STDERR}" "characters of context" "G3 block message reports the payload count"
assert_contains "${HOOK_STDERR}" "only $(cat "${TMP}/fable_text_chars.txt") characters of your text" \
    "G3 counts every turn-opening text block back to the human's message, not just the last injected entry"

run_hook "AskUserQuestion" "${TMP}/bare.json" "${TMP}/t_injected_skip.jsonl"
assert_eq "$?" "0" "harness-injected user entries (isMeta, system-reminder, local-command, image companion) do not start a turn"

run_hook "AskUserQuestion" "${TMP}/bare.json" "${TMP}/t_reminder_in_real.jsonl"
assert_eq "$?" "2" "a real user message with an appended reminder block is still a turn boundary"

run_hook "AskUserQuestion" "${TMP}/bare.json" "${TMP}/t_command_boundary.jsonl"
assert_eq "$?" "2" "a typed slash command is a turn boundary"

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

run_hook "AskUserQuestion" "${TMP}/thin.json" "${TMP}/t_malformed.jsonl"
assert_eq "$?" "2" "malformed transcript lines are skipped, valid entries still gate (G3)"

ASK_CONTEXT_MIN_CHARS=1000 run_hook "AskUserQuestion" "${TMP}/thin.json" "${TMP}/t_midturn_brief.jsonl"
assert_eq "$?" "2" "ASK_CONTEXT_MIN_CHARS overrides the transcript threshold (raised past the brief)"

ASK_CONTEXT_MIN_CHARS=1000 run_hook "AskUserQuestion" "${TMP}/self.json" "${TMP}/t_payload_dark.jsonl"
assert_eq "$?" "2" "ASK_CONTEXT_MIN_CHARS overrides the payload threshold too"

# ─── Summary ─────────────────────────────────────────────────────────────────
echo ""
echo "ask-context-gate: ${PASS} passed, ${FAIL} failed"
[ "${FAIL}" -eq 0 ] || exit 1
exit 0
