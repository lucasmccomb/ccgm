#!/usr/bin/env bash
# Tests for the selection and routing half of the analyzer
# (lib/draft_proposals.py plan, #1099 Phase 2.2). This file replaced the
# day-payload clustering tests: routine tool_use is no longer sent, so what
# needs pinning is which signatures are chosen and which files they get.
#
# Coverage:
#   - at most 3 signatures, ranked by count x sessions; below-bar ones skipped
#   - signatures with a proposal row, or snoozed, are not chosen
#   - candidates: cmd_head map, error_class map, keyword fallback, none
#   - at most 2 candidate files; all other paths stay out of the prompt
#   - hook denials become `issue` rows and never produce a request
#   - the system prefix is identical across signatures (cacheable)
#   - the schema sent to the model is pinned to the candidates and holds no
#     keyword the structured-outputs subset rejects
#   - the excerpt is one redacted block of 1,500 characters or less

set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MODULE_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
# shellcheck source=analyzer-fixture.sh
. "${SCRIPT_DIR}/analyzer-fixture.sh"

PASS=0
FAIL=0
TODAY="2026-10-04"
ROOT=$(mktemp -d -t autoheal_plan.XXXXXX)
trap 'rm -rf "${ROOT}"' EXIT

scenario() {
    S_ROOT="${ROOT}/$1"
    S_HOME="${S_ROOT}/home"
    S_AH="${S_HOME}/.claude/autoheal"
    S_OUT="${S_ROOT}/out"
    mkdir -p "${S_AH}"
    fx_repo "${S_ROOT}/repo"
    fx_home "${S_HOME}" "${S_ROOT}/repo"
}

# plan: aggregate, then plan. Leaves plan.tsv and item files in S_OUT.
plan() {
    env HOME="${S_HOME}" CCGM_AUTOHEAL_DIR="${S_AH}" CCGM_AUTOHEAL_TODAY="${TODAY}" \
        python3 "${MODULE_ROOT}/bin/autoheal-aggregate.py" --date "${TODAY}" >/dev/null
    env HOME="${S_HOME}" CCGM_AUTOHEAL_DIR="${S_AH}" CCGM_AUTOHEAL_TODAY="${TODAY}" \
        python3 "${MODULE_ROOT}/lib/draft_proposals.py" plan --date "${TODAY}" --out "${S_OUT}" \
        --model claude-sonnet-5 --max-tokens 2000 \
        --prompt "${MODULE_ROOT}/lib/analyzer-prompt.md" >"${S_ROOT}/plan.out" 2>"${S_ROOT}/plan.err"
    PLAN_RC=$?
}
tsv() { cat "${S_OUT}/plan.tsv"; }
candidates_of() { json_get "${S_OUT}/item-$1.json" "' '.join(d['candidates'])"; }

# --- ranking and the cap of three ------------------------------------
scenario rank
for spec in "echo:zsh_not_found:5" "grep:zsh_no_matches:9" "ls:no_such_file:7" "cat:no_such_file:6" "cp:permission_denied:8"; do
    IFS=: read -r head cls n <<< "${spec}"
    fx_events "${S_AH}" "${TODAY}" Bash "${head}" "${cls}" "boom" "${n}" 2
done
fx_events "${S_AH}" "${TODAY}" Bash rm no_such_file "below the bar" 4 2
plan
assert_eq "${PLAN_RC}" "0" "rank: plan exits 0"
assert_eq "$(grep -c '^item' "${S_OUT}/plan.tsv")" "3" "rank: three items"
assert_eq "$(head -1 "${S_OUT}/plan.tsv")" "$(printf 'selected\t3\t-')" "rank: selected = 3 even with 6 signatures"
assert_eq "$(for i in 1 2 3; do json_get "${S_OUT}/item-$i.json" "d['signature']['count']"; done | tr '\n' ' ')" "9 8 7 " "rank: highest count x sessions first"
assert_eq "$(ls "${S_OUT}"/item-*.request.json | wc -l | tr -d ' ')" "3" "rank: one request per item"

# --- coverage and snooze ---------------------------------------------
scenario covered
fx_events "${S_AH}" "${TODAY}" Bash echo zsh_not_found "boom" 8 2
fx_events "${S_AH}" "${TODAY}" Bash grep zsh_no_matches "boom" 8 2
fx_events "${S_AH}" "${TODAY}" Bash ls no_such_file "boom" 8 2
COVERED_ID="$(python3 -c "
import hashlib
print(hashlib.sha256('\x1f'.join(('Bash','echo','zsh_not_found')).encode()).hexdigest()[:12])")"
SNOOZED_ID="$(python3 -c "
import hashlib
print(hashlib.sha256('\x1f'.join(('Bash','grep','zsh_no_matches')).encode()).hexdigest()[:12])")"
mkdir -p "${S_AH}"
printf '{"id":"%s","signature_id":"%s","state":"ready"}\n' "${COVERED_ID}" "${COVERED_ID}" > "${S_AH}/proposals.jsonl"
printf '{"%s":{"snoozed_until":"2026-12-01T00:00:00Z"}}\n' "${SNOOZED_ID}" > "${S_AH}/snoozed.json"
plan
assert_eq "$(grep -c '^item' "${S_OUT}/plan.tsv")" "1" "covered: a covered and a snoozed signature are not chosen"
assert_eq "$(json_get "${S_OUT}/item-1.json" "d['signature']['cmd_head']")" "ls" "covered: the remaining one is chosen"

# --- candidate files --------------------------------------------------
# cand_case <name> <cmd_head> <error_class>: one signature in a fresh scenario.
cand_case() {
    scenario "cand_$1"
    fx_events "${S_AH}" "${TODAY}" Bash "$2" "$3" "boom" 6 3
    plan
}
cand_case shell echo zsh_not_found
assert_eq "$(candidates_of 1)" "modules/code-quality/rules/code-quality.md modules/common-mistakes/rules/common-mistakes.md" "cands: shell error class -> code-quality and common-mistakes"
cand_case gitzsh "git add" zsh_no_matches
assert_eq "$(candidates_of 1)" "modules/git-workflow/rules/git-workflow.md modules/code-quality/rules/code-quality.md" "cands: git head first, then the error class, capped at 2"
cand_case gitpath "git commit" pathspec_no_match
assert_eq "$(candidates_of 1)" "modules/git-workflow/rules/git-workflow.md" "cands: git pathspec -> git-workflow only"
cand_case keyword pages other
assert_eq "$(candidates_of 1)" "modules/cloudflare/rules/cloudflare.md" "cands: keyword fallback matches the index"
cand_case none zzzz other
NONE_ID="$(json_get "${S_AH}/signatures/${TODAY}.json" "d['signatures'][0]['signature_id']")"
assert_contains "$(tsv)" "note	${NONE_ID}	no_candidates" "cands: nothing maps -> a no_candidates note, no request"
assert_eq "$(grep -c '^item' "${S_OUT}/plan.tsv")" "0" "cands: ...and no request"

# --- prompt content: only candidates in full --------------------------
cand_case prompt "git commit" pathspec_no_match
USER_TEXT="$(json_get "${S_OUT}/item-1.request.json" "d['messages'][0]['content']")"
assert_contains "${USER_TEXT}" "Pathspecs Resolve From cwd" "prompt: candidate text is included in full"
assert_not_contains "${USER_TEXT}" "Pages vs Workers" "prompt: other rule files are not included"
assert_not_contains "${USER_TEXT}" "Escape Hatch" "prompt: index headings stay in the cached prefix, not the user message"

# --- cacheable prefix and schema ---------------------------------------
scenario prefix
fx_events "${S_AH}" "${TODAY}" Bash echo zsh_not_found "boom" 6 3
fx_events "${S_AH}" "${TODAY}" Bash "git add" pathspec_no_match "boom" 8 3
plan
SYS_A="$(json_get "${S_OUT}/item-1.request.json" "json.dumps(d['system'], sort_keys=True)")"
SYS_B="$(json_get "${S_OUT}/item-2.request.json" "json.dumps(d['system'], sort_keys=True)")"
assert_eq "$([ "${SYS_A}" = "${SYS_B}" ] && echo same || echo different)" "same" "prefix: system blocks are identical across signatures"
assert_eq "$(json_get "${S_OUT}/item-1.request.json" "[b.get('cache_control',{}).get('type') for b in d['system']]")" "[None, 'ephemeral']" "prefix: breakpoint after the module index"
assert_contains "$(json_get "${S_OUT}/item-1.request.json" "d['system'][1]['text']")" "modules/branch-guard/rules/branch-guard.md" "prefix: index lists every rule file"
assert_eq "$(json_get "${S_OUT}/item-1.request.json" "'maxLength' in json.dumps(d['output_config'])")" "False" "schema: no keyword the structured-outputs subset rejects"
assert_eq "$(json_get "${S_OUT}/item-1.request.json" "sorted(d['output_config']['format']['schema']['properties']['proposal']['anyOf'][0]['properties']['target_path']['enum']) == sorted(json.load(open('${S_OUT}/item-1.json'))['candidates'])")" "True" "schema: target_path enum == the candidates"
assert_eq "$(json_get "${S_OUT}/item-1.request.json" "[b['properties']['kind']['enum'][0] for b in d['output_config']['format']['schema']['properties']['proposal']['anyOf']]")" "['rule_insert', 'skip']" "schema: exactly two kinds"
assert_eq "$(json_get "${S_OUT}/item-1.count.json" "sorted(d)")" "['messages', 'model', 'system']" "count body: model, system, messages only"

# --- hook denials ------------------------------------------------------
scenario hooks
fx_events "${S_AH}" "${TODAY}" Edit "" hook_denial_branch_guard "BRANCH GUARD: x" 6 2
fx_events "${S_AH}" "${TODAY}" Bash "" hook_denial_advisor_guard "advisor mode: x" 6 2
fx_events "${S_AH}" "${TODAY}" Bash "git push" hook_denial_git_workflow "Blocked: force-push" 6 2
plan
assert_eq "$(grep -c '^item' "${S_OUT}/plan.tsv")" "0" "hooks: no model request for a hook denial"
assert_eq "$(ls "${S_OUT}"/item-* 2>/dev/null | wc -l | tr -d ' ')" "0" "hooks: no request files at all"
PROP="${S_AH}/proposals.jsonl"
assert_eq "$(python3 -c "
import json
print(sorted((r['kind'], r['module']) for r in map(json.loads, open('${PROP}'))))")" \
    "[('issue', 'advisor-mode'), ('issue', 'branch-guard'), ('issue', 'git-workflow')]" "hooks: one issue per denying module"
assert_eq "$(jsonl_get "${PROP}" 1 "d['issue_title'] != '' and 'fix_surface' in d")" "True" "hooks: issue rows carry a drafted title"
assert_not_contains "$(cat "${PROP}")" "github.com" "hooks: nothing is filed; the row holds only local text"

# --- excerpt -----------------------------------------------------------
scenario excerpt
python3 - "${S_AH}" "${TODAY}" <<'PY'
import datetime as dt, json, os, sys
state, end = sys.argv[1], dt.date.fromisoformat(sys.argv[2])
os.makedirs(state + "/events", exist_ok=True)
for i in range(8):
    day = (end - dt.timedelta(days=i % 2)).isoformat()
    row = {"kind": "tool_failure", "timestamp": f"{day}T10:{i:02d}:00+00:00", "session_id": f"s-{i % 3}",
           "tool_name": "Bash", "cmd_head": "curl", "error_class": "command_not_found",
           "error": "curl: command not found " + "x" * 3000,
           "redacted_command": "curl -H 'Authorization: Bearer sk-ant-api03-" + "A" * 40 + "' https://example.test " + "y" * 3000,
           "cwd": "/Users/someone/code/demo-0"}
    with open(f"{state}/events/{day}.jsonl", "a") as fh:
        fh.write(json.dumps(row) + "\n")
PY
plan
EX_ITEM=1
EX_TEXT="$(json_get "${S_OUT}/item-${EX_ITEM}.request.json" "d['messages'][0]['content']")"
assert_contains "${EX_TEXT}" "Excerpt of the most recent occurrence" "excerpt: section present"
assert_not_contains "${EX_TEXT}" "sk-ant-api03-AAAA" "excerpt: secrets are redacted"
EX_LEN="$(python3 - "${S_OUT}/item-${EX_ITEM}.request.json" <<'PY'
import json, re, sys
text = json.load(open(sys.argv[1]))["messages"][0]["content"]
block = text.split("## Excerpt of the most recent occurrence", 1)[1]
body = re.split(r"```text\n", block, maxsplit=1)[1].rsplit("\n```", 1)[0]
print(len(body))
PY
)"
assert_eq "$([ "${EX_LEN}" -le 1500 ] && echo ok || echo "too long: ${EX_LEN}")" "ok" "excerpt: 1,500 characters or less"
assert_eq "$(grep -o '## Excerpt' <<< "${EX_TEXT}" | wc -l | tr -d ' ')" "1" "excerpt: exactly one"

echo ""
echo "test-analyzer-clustering.sh: ${PASS} passed, ${FAIL} failed"
[ "${FAIL}" -eq 0 ]
