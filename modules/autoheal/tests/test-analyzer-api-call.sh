#!/usr/bin/env bash
# Tests for modules/autoheal/bin/autoheal-analyze.sh: the drafting flow of
# #1099 Phase 2.2. The analyzer aggregates signatures, sends at most three
# small prompts, and builds the diff itself. Nothing here calls the network:
# tests/fixtures/fake-curl.py stands in for curl on PATH.
#
# Coverage:
#   - zsh-quoting signature -> rule_insert whose target exists and whose diff
#     passes `git apply --check` in a fixture repo; id == signature_id
#   - request shape: model, max_tokens 2000, thinking off, enum-constrained
#     target_path, cache_control on the stable prefix, no transcript dump
#   - input measured through count_tokens; > 15k tokens is refused unsent
#   - anchor_missing / path_not_candidate / skip handling
#   - hook-denial signature -> `issue` proposal, no model call
#   - no qualifying signature -> zero API calls; missing key, cost cap,
#     unsupported model, no source repo -> zero messages calls
#   - failed calls are not retried; at most 3 signatures per run
#   - per-model pricing and the cache-token cost terms
#   - the calibration / SHA counter / rejected-day hold are gone

set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MODULE_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
ANALYZER="${MODULE_ROOT}/bin/autoheal-analyze.sh"
# shellcheck source=analyzer-fixture.sh
. "${SCRIPT_DIR}/analyzer-fixture.sh"

PASS=0
FAIL=0
TODAY="2026-10-04"
ROOT=$(mktemp -d -t autoheal_api.XXXXXX)
trap 'rm -rf "${ROOT}"' EXIT

ZSH_ANSWER='{"proposal":{"kind":"rule_insert","target_path":"modules/code-quality/rules/code-quality.md","anchor_heading":"Code Standards","insert_markdown":"- Bash runs under zsh. Quote `====` separators and glob flags such as `--include='"'"'*.sh'"'"'`."}}'

# scenario <name>: fresh repo, HOME, state dir, fake curl. Sets S_* globals.
scenario() {
    S_ROOT="${ROOT}/$1"
    S_REPO="${S_ROOT}/repo"
    S_HOME="${S_ROOT}/home"
    S_AH="${S_HOME}/.claude/autoheal"
    S_BIN="${S_ROOT}/bin"
    S_FAKE="${S_ROOT}/fake"
    mkdir -p "${S_AH}"
    fx_repo "${S_REPO}"
    fx_home "${S_HOME}" "${S_REPO}"
    fx_curl "${S_BIN}" "${S_FAKE}"
}

# zsh_events: 12 zsh "== not found" failures over 3 sessions and 2 days.
zsh_events() {
    fx_events "${S_AH}" "${TODAY}" Bash echo zsh_not_found "(eval):1: ==== not found" 12 3
}

# run_analyzer [extra env assignments...]: runs the analyzer in the scenario.
run_analyzer() {
    env HOME="${S_HOME}" PATH="${S_BIN}:${PATH}" FAKE_CURL_DIR="${S_FAKE}" \
        CCGM_AUTOHEAL_DIR="${S_AH}" CCGM_AUTOHEAL_TODAY="${TODAY}" \
        CCGM_AUTOHEAL_CLONE_ID="ccgm-w1-c0" ANTHROPIC_API_KEY="sk-test-not-real" \
        "$@" bash "${ANALYZER}" >"${S_ROOT}/run.out" 2>"${S_ROOT}/run.err"
    RC=$?
    ERR="$(cat "${S_ROOT}/run.err")"
}

# ---------------------------------------------------------------------
# Test 1 - zsh signature -> rule_insert, diff applies, request is small.
# ---------------------------------------------------------------------
scenario t1
zsh_events
fx_answer "${S_FAKE}/messages.response.json" "${ZSH_ANSWER}"
echo '{"input_tokens": 9000}' > "${S_FAKE}/count_tokens.response.json"
PROMPT_LOG="${S_ROOT}/prompt.log"
run_analyzer CCGM_AUTOHEAL_PROMPT_LOG="${PROMPT_LOG}"
assert_eq "${RC}" "0" "t1: analyzer exits 0"
assert_eq "$(fx_calls "${S_FAKE}" count_tokens)" "1" "t1: one count_tokens call"
assert_eq "$(fx_calls "${S_FAKE}" messages)" "1" "t1: one messages call"

P1="${S_AH}/proposals/${TODAY}.jsonl"
assert_file_exists "${P1}" "t1: proposals file written"
assert_eq "$(wc -l < "${P1}" | tr -d ' ')" "1" "t1: exactly one row"
SIG_ID="$(python3 -c "
import json
d=json.load(open('${S_AH}/signatures/${TODAY}.json'))
print([s for s in d['signatures'] if s['qualifies']][0]['signature_id'])")"
assert_eq "$(jsonl_get "${P1}" 1 "d['signature_id']")" "${SIG_ID}" "t1: signature_id is the aggregator's"
assert_eq "$(jsonl_get "${P1}" 1 "d['id']")" "${SIG_ID}" "t1: id == signature_id (sha256(signature)[:12])"
assert_eq "$(jsonl_get "${P1}" 1 "d['kind']")" "rule_insert" "t1: kind"
assert_eq "$(jsonl_get "${P1}" 1 "d['state']")" "ready" "t1: state ready"
assert_eq "$(jsonl_get "${P1}" 1 "d['target']")" "modules/code-quality/rules/code-quality.md" "t1: target"
assert_eq "$(jsonl_get "${P1}" 1 "d['anchor']")" "Code Standards" "t1: anchor"
assert_contains "$(jsonl_get "${P1}" 1 "d['insert_markdown']")" "Bash runs under zsh" "t1: insert text kept"
assert_eq "$(jsonl_get "${P1}" 1 "d['evidence']['count']")" "12" "t1: evidence count"
assert_eq "$(jsonl_get "${P1}" 1 "d['evidence']['sessions']")" "3" "t1: evidence sessions"
assert_contains "$(jsonl_get "${P1}" 1 "d['evidence']['samples']")" "not found" "t1: evidence sample errors"
assert_eq "$(jsonl_get "${P1}" 1 "d['originating_clone']")" "ccgm-w1-c0" "t1: originating_clone"
assert_eq "$(jsonl_get "${P1}" 1 "d['proposed_diff_target']")" "modules/code-quality/rules/code-quality.md" "t1: apply-path target alias"

# The diff is built by code and applies to the real file.
jsonl_get "${P1}" 1 "d['diff']" > "${S_ROOT}/t1.diff"
git -C "${S_REPO}" apply --check "${S_ROOT}/t1.diff" 2>"${S_ROOT}/apply.err"
assert_eq "$?" "0" "t1: generated diff passes git apply --check ($(cat "${S_ROOT}/apply.err"))"
assert_contains "$(cat "${S_ROOT}/t1.diff")" "+- Bash runs under zsh" "t1: diff adds the insert text"
assert_contains "$(cat "${S_ROOT}/t1.diff")" "--- a/modules/code-quality/rules/code-quality.md" "t1: diff names the real file"
# The insert lands inside the anchored section, before the next heading.
git -C "${S_REPO}" apply "${S_ROOT}/t1.diff"
SECTION="$(sed -n '/^## Code Standards/,/^## Testing/p' "${S_REPO}/modules/code-quality/rules/code-quality.md")"
assert_contains "${SECTION}" "Bash runs under zsh" "t1: insert sits under its anchor heading"
git -C "${S_REPO}" checkout -q -- .

# Request shape.
REQ="${S_FAKE}/messages-1.request.json"
assert_eq "$(json_get "${REQ}" "d['model']")" "claude-sonnet-5" "t1: model"
assert_eq "$(json_get "${REQ}" "d['max_tokens']")" "2000" "t1: max_tokens 2000"
assert_eq "$(json_get "${REQ}" "d['thinking']['type']")" "disabled" "t1: thinking off"
assert_eq "$(json_get "${REQ}" "sorted(d['output_config']['format']['schema']['properties']['proposal']['anyOf'][0]['properties']['target_path']['enum'])")" \
    "['modules/code-quality/rules/code-quality.md', 'modules/common-mistakes/rules/common-mistakes.md']" \
    "t1: target_path enum is exactly the candidate files"
assert_eq "$(json_get "${REQ}" "d['system'][-1].get('cache_control',{}).get('type')")" "ephemeral" "t1: stable prefix marked for caching"
assert_contains "$(json_get "${REQ}" "d['system'][-1]['text']")" "modules/git-workflow/rules/git-workflow.md" "t1: module index is in the prefix"
USER_TEXT="$(json_get "${REQ}" "d['messages'][0]['content']")"
assert_contains "${USER_TEXT}" "## Code Standards" "t1: full candidate file text is sent"
assert_contains "${USER_TEXT}" "==== not found" "t1: sample error is sent"
assert_not_contains "${USER_TEXT}" "git-workflow.md" "t1: non-candidate files are not sent in full"
assert_eq "$(python3 -c "print(1 if len(open('${REQ}').read()) < 60000 else 0)")" "1" "t1: request is small"
# count_tokens saw the same prompt without the output-only fields.
CREQ="${S_FAKE}/count_tokens-1.request.json"
assert_eq "$(json_get "${CREQ}" "d['model']")" "claude-sonnet-5" "t1: count_tokens body carries the model"
assert_eq "$(json_get "${CREQ}" "d['messages'] == json.load(open('${REQ}'))['messages']")" "True" "t1: count_tokens measures the real messages"
assert_file_exists "${PROMPT_LOG}" "t1: prompt log written"

# Cost log and run summary.
assert_eq "$(awk -F'\t' '{print $1"|"$2"|"$3"|"$4"|"$5}' "${S_AH}/cost.log")" "${TODAY}|1200|240|0.004800|claude-sonnet-5" "t1: cost.log row"
assert_eq "$(json_get "${S_AH}/runs/${TODAY}.json" "d['failed_calls']")" "0" "t1: runs summary written, no failures"

# The existing digest renders the row; the apply command reads the same id.
digest_for() {
    CCGM_AUTOHEAL_PROPOSALS_DIR="${S_AH}/proposals" CCGM_AUTOHEAL_DIGESTS_DIR="${S_AH}/digests" \
        CCGM_AUTOHEAL_SENT_DIR="${S_AH}/sent" CCGM_AUTOHEAL_CONFIG="${S_AH}/none.json" \
        CCGM_AUTOHEAL_TODAY="${TODAY}" CCGM_AUTOHEAL_LIB_DIR="${MODULE_ROOT}/../hooks/lib" \
        HOME="${S_HOME}" bash "${MODULE_ROOT}/bin/autoheal-digest.sh" >/dev/null 2>&1
    cat "${S_AH}/digests/${TODAY}.md" 2>/dev/null
}
DIGEST_BODY="$(digest_for)"
assert_contains "${DIGEST_BODY}" "/autoheal-apply ${SIG_ID}" "t1: digest renders the proposal with its apply command"
assert_contains "${DIGEST_BODY}" "add a rule to code-quality.md" "t1: digest shows the title"

# A second run drafts nothing: the signature now has a proposal.
rm -f "${S_FAKE}/calls.log"
run_analyzer
assert_eq "${RC}" "0" "t1b: rerun exits 0"
assert_eq "$(fx_calls "${S_FAKE}" messages)" "0" "t1b: covered signature is not sent again"
assert_contains "${ERR}" "no qualifying" "t1b: rerun logs that nothing qualifies"

# ---------------------------------------------------------------------
# Test 2 - input over 15k tokens (measured by count_tokens) is refused.
# ---------------------------------------------------------------------
scenario t2
zsh_events
fx_answer "${S_FAKE}/messages.response.json" "${ZSH_ANSWER}"
echo '{"input_tokens": 15001}' > "${S_FAKE}/count_tokens.response.json"
run_analyzer
assert_eq "$(fx_calls "${S_FAKE}" count_tokens)" "1" "t2: input was measured"
assert_eq "$(fx_calls "${S_FAKE}" messages)" "0" "t2: 15001 tokens is never sent"
assert_contains "${ERR}" "input_over_limit" "t2: refusal is logged with its reason"
assert_eq "$(json_get "${S_AH}/runs/${TODAY}.json" "d['failed_calls']")" "1" "t2: refusal counts as a failed call"
assert_eq "${RC}" "1" "t2: refusal makes the run exit non-zero"
assert_no_file "${S_AH}/cost.log" "t2: nothing was spent"

scenario t2b
zsh_events
fx_answer "${S_FAKE}/messages.response.json" "${ZSH_ANSWER}"
echo '{"input_tokens": 15000}' > "${S_FAKE}/count_tokens.response.json"
run_analyzer
assert_eq "$(fx_calls "${S_FAKE}" messages)" "1" "t2b: exactly 15000 tokens is allowed"

scenario t2c
zsh_events
echo '{"type":"error"}' > "${S_FAKE}/count_tokens.response.json"
echo 400 > "${S_FAKE}/count_tokens.status"
run_analyzer
assert_eq "$(fx_calls "${S_FAKE}" messages)" "0" "t2c: a failed measurement blocks the paid call"
assert_contains "${ERR}" "count_tokens_http_400" "t2c: failure reason names the status"

# ---------------------------------------------------------------------
# Test 3 - code-side checks drop bad answers with a counted reason.
# ---------------------------------------------------------------------
scenario t3
zsh_events
BAD_ANCHOR='{"proposal":{"kind":"rule_insert","target_path":"modules/code-quality/rules/code-quality.md","anchor_heading":"No Such Heading","insert_markdown":"- x"}}'
fx_answer "${S_FAKE}/messages.response.json" "${BAD_ANCHOR}"
run_analyzer
assert_eq "${RC}" "0" "t3: a dropped proposal is not a failed run"
assert_no_file "${S_AH}/proposals/${TODAY}.jsonl" "t3: anchor_missing writes no proposal"
assert_contains "$(cat "${S_HOME}/.claude/logs/autoheal-rejected-${TODAY}.log")" "anchor_missing" "t3: rejection log names anchor_missing"
assert_eq "$(json_get "${S_AH}/runs/${TODAY}.json" "d['dropped']['anchor_missing']")" "1" "t3: runs summary counts anchor_missing"
assert_contains "${ERR}" "anchor_missing" "t3: stderr names anchor_missing"

scenario t3b
zsh_events
BAD_PATH='{"proposal":{"kind":"rule_insert","target_path":"modules/invented/rules/made-up.md","anchor_heading":"Code Standards","insert_markdown":"- x"}}'
fx_answer "${S_FAKE}/messages.response.json" "${BAD_PATH}"
run_analyzer
assert_no_file "${S_AH}/proposals/${TODAY}.jsonl" "t3b: invented path writes no proposal"
assert_eq "$(json_get "${S_AH}/runs/${TODAY}.json" "d['dropped']['path_not_candidate']")" "1" "t3b: runs summary counts path_not_candidate"

scenario t3c
zsh_events
SKIP='{"proposal":{"kind":"skip","reason":"the failure is environmental"}}'
fx_answer "${S_FAKE}/messages.response.json" "${SKIP}"
run_analyzer
assert_eq "${RC}" "0" "t3c: skip exits 0"
P3C="${S_AH}/proposals/${TODAY}.jsonl"
assert_eq "$(jsonl_get "${P3C}" 1 "d['state']")" "skipped" "t3c: skip is recorded with state skipped"
assert_eq "$(jsonl_get "${P3C}" 1 "d['reason']")" "the failure is environmental" "t3c: skip reason kept"
assert_not_contains "$(digest_for)" "skipped:" "t3c: the digest does not list a skipped row as a proposal"
rm -f "${S_FAKE}/calls.log"
run_analyzer
assert_eq "$(fx_calls "${S_FAKE}" messages)" "0" "t3c: a skipped signature is not re-sent"

# ---------------------------------------------------------------------
# Test 4 - hook denials never reach the model.
# ---------------------------------------------------------------------
scenario t4
fx_events "${S_AH}" "${TODAY}" Edit "" hook_denial_branch_guard "BRANCH GUARD: no edits on main" 8 2
run_analyzer
assert_eq "${RC}" "0" "t4: exits 0"
assert_eq "$(fx_calls "${S_FAKE}" count_tokens)" "0" "t4: no count_tokens call"
assert_eq "$(fx_calls "${S_FAKE}" messages)" "0" "t4: no model call for a hook denial"
P4="${S_AH}/proposals/${TODAY}.jsonl"
assert_eq "$(jsonl_get "${P4}" 1 "d['kind']")" "issue" "t4: proposal kind is issue"
assert_eq "$(jsonl_get "${P4}" 1 "d['state']")" "ready" "t4: issue is ready"
assert_eq "$(jsonl_get "${P4}" 1 "d['module']")" "branch-guard" "t4: names the denying hook's module"
assert_eq "$(jsonl_get "${P4}" 1 "d['evidence']['count']")" "8" "t4: evidence carried"
assert_contains "$(jsonl_get "${P4}" 1 "d['issue_body']")" "BRANCH GUARD" "t4: issue body drafted locally with the sample error"
assert_eq "$(jsonl_get "${P4}" 1 "'diff' in d")" "False" "t4: an issue carries no diff"
assert_no_file "${S_AH}/cost.log" "t4: no spend"

# Hook denial works without an API key and without a source repo.
scenario t4b
fx_events "${S_AH}" "${TODAY}" Edit "" hook_denial_advisor_guard "advisor mode: delegate this" 6 2
rm -rf "${S_HOME}/.claude/rules"
run_analyzer ANTHROPIC_API_KEY=
assert_eq "${RC}" "0" "t4b: exits 0 with no key and no repo"
assert_eq "$(jsonl_get "${S_AH}/proposals/${TODAY}.jsonl" 1 "d['kind']")" "issue" "t4b: issue still drafted locally"

# ---------------------------------------------------------------------
# Test 5 - nothing qualifies: zero API calls.
# ---------------------------------------------------------------------
scenario t5
fx_events "${S_AH}" "${TODAY}" Bash echo zsh_not_found "(eval):1: ==== not found" 4 3
run_analyzer
assert_eq "${RC}" "0" "t5: exits 0"
assert_no_file "${S_FAKE}/calls.log" "t5: zero API calls"
assert_contains "${ERR}" "no qualifying" "t5: logs that no signature qualified"
assert_no_file "${S_AH}/proposals/${TODAY}.jsonl" "t5: no proposals"

scenario t5b
run_analyzer
assert_eq "${RC}" "0" "t5b: no events at all exits 0"
assert_no_file "${S_FAKE}/calls.log" "t5b: zero API calls with no events"

# ---------------------------------------------------------------------
# Test 6 - guards that stop a paid call before it is made.
# ---------------------------------------------------------------------
scenario t6a
zsh_events
run_analyzer ANTHROPIC_API_KEY=
assert_eq "${RC}" "0" "t6a: no API key exits 0"
assert_eq "$(fx_calls "${S_FAKE}" messages)" "0" "t6a: no key, no call"
assert_contains "${ERR}" "ANTHROPIC_API_KEY" "t6a: says why"

scenario t6b
zsh_events
printf '%s\t1\t1\t10.500000\tclaude-sonnet-5\n' "${TODAY}" > "${S_AH}/cost.log"
run_analyzer
assert_eq "${RC}" "2" "t6b: daily cost cap exits 2"
assert_eq "$(fx_calls "${S_FAKE}" messages)" "0" "t6b: cap reached, no call"

scenario t6c
zsh_events
echo '{"default_model": "claude-sonnet-4-6"}' > "${S_AH}/config.json"
run_analyzer
assert_eq "${RC}" "2" "t6c: a model without structured outputs exits 2"
assert_eq "$(fx_calls "${S_FAKE}" messages)" "0" "t6c: nothing sent"
assert_contains "${ERR}" "does not support structured outputs" "t6c: names the problem"

scenario t6d
zsh_events
rm -rf "${S_HOME}/.claude/rules"
run_analyzer
assert_eq "${RC}" "0" "t6d: copy install (no source repo) exits 0"
assert_no_file "${S_FAKE}/calls.log" "t6d: no calls without a source repo"
assert_contains "${ERR}" "no_source_repo" "t6d: logged reason"
assert_no_file "${S_AH}/proposals/${TODAY}.jsonl" "t6d: no invented proposal"

scenario t6e
zsh_events
rm -rf "${S_HOME}/.claude/rules"
printf '{"ccgm_repo_path": "%s"}\n' "${S_REPO}" > "${S_AH}/config.json"
fx_answer "${S_FAKE}/messages.response.json" "${ZSH_ANSWER}"
run_analyzer
assert_eq "$(fx_calls "${S_FAKE}" messages)" "1" "t6e: ccgm_repo_path config key supplies the source repo"

# ---------------------------------------------------------------------
# Test 7 - failed calls are not retried or held.
# ---------------------------------------------------------------------
scenario t7a
zsh_events
echo '{"type":"error","error":{"message":"overloaded"}}' > "${S_FAKE}/messages.response.json"
echo 529 > "${S_FAKE}/messages.status"
run_analyzer
assert_eq "${RC}" "1" "t7a: HTTP failure exits 1"
assert_eq "$(fx_calls "${S_FAKE}" messages)" "1" "t7a: a failed call is not retried in-run"
assert_eq "$(json_get "${S_AH}/runs/${TODAY}.json" "d['failed_calls']")" "1" "t7a: failure counted"
assert_no_file "${S_AH}/rejected-days.jsonl" "t7a: no rejected-days ledger"
assert_no_file "${S_AH}/proposals/${TODAY}.jsonl" "t7a: no proposal"

scenario t7b
zsh_events
fx_answer "${S_FAKE}/messages.response.json" '{"proposal":{"kind":"skip","reason":"cut"}}' max_tokens
run_analyzer
assert_eq "${RC}" "1" "t7b: stop_reason max_tokens is a failed call"
assert_eq "$(json_get "${S_AH}/runs/${TODAY}.json" "d['truncated_calls']")" "1" "t7b: truncation counted"
assert_no_file "${S_AH}/proposals/${TODAY}.jsonl" "t7b: truncated answer is not used"
assert_eq "$(awk -F'\t' '{print $2}' "${S_AH}/cost.log")" "1200" "t7b: a billed call is still in cost.log"

scenario t7c
zsh_events
fx_answer "${S_FAKE}/messages.response.json" "" end_turn
run_analyzer
assert_eq "${RC}" "1" "t7c: empty response is a failed call"
assert_contains "${ERR}" "empty_response_text" "t7c: names the reason"

scenario t7d
zsh_events
echo 28 > "${S_FAKE}/messages.curl_exit"
run_analyzer
assert_eq "${RC}" "1" "t7d: transport failure exits 1"
assert_contains "${ERR}" "transport_exit_28" "t7d: names the reason"

# ---------------------------------------------------------------------
# Test 8 - at most three signatures per run, ranked.
# ---------------------------------------------------------------------
scenario t8
for spec in "echo:zsh_not_found:5" "grep:zsh_no_matches:9" "ls:no_such_file:7" "cat:no_such_file:6" "cp:permission_denied:8"; do
    IFS=: read -r head cls n <<< "${spec}"
    fx_events "${S_AH}" "${TODAY}" Bash "${head}" "${cls}" "boom ${cls}" "${n}" 2
done
fx_answer "${S_FAKE}/messages.response.json" '{"proposal":{"kind":"skip","reason":"no rule helps"}}'
run_analyzer
assert_eq "$(fx_calls "${S_FAKE}" messages)" "3" "t8: five qualify, three are drafted"
assert_eq "$(fx_calls "${S_FAKE}" count_tokens)" "3" "t8: three measurements"
assert_eq "$(wc -l < "${S_AH}/proposals/${TODAY}.jsonl" | tr -d ' ')" "3" "t8: three rows"
TOP="$(python3 -c "
import json
rows=[json.loads(l) for l in open('${S_AH}/proposals/${TODAY}.jsonl')]
print(sorted(r['evidence']['count'] for r in rows))")"
assert_eq "${TOP}" "[7, 8, 9]" "t8: the three highest count x sessions go first"

# ---------------------------------------------------------------------
# Test 9 - pricing and cache terms.
# ---------------------------------------------------------------------
cost_for() {
    # cost_for <model> <config json or ""> <in> <out> [cache_create] [cache_read]
    scenario "cost_$1_$3_${5:-0}"
    zsh_events
    [ -n "$2" ] && printf '%s\n' "$2" > "${S_AH}/config.json"
    fx_answer "${S_FAKE}/messages.response.json" "${ZSH_ANSWER}" end_turn "$3" "$4" "${5:-0}" "${6:-0}"
    run_analyzer
    COST="$(awk -F'\t' '{print $4}' "${S_AH}/cost.log")"
    LOGGED_MODEL="$(awk -F'\t' '{print $5}' "${S_AH}/cost.log")"
    LOGGED_IN="$(awk -F'\t' '{print $2}' "${S_AH}/cost.log")"
}
PRICES='"cost_pricing": {"claude-sonnet-5": {"input_per_million": 2, "output_per_million": 10}, "claude-opus-4-8": {"input_per_million": 5, "output_per_million": 25}}'
cost_for sonnet "{\"default_model\": \"claude-sonnet-5\", ${PRICES}}" 1200 240
assert_eq "${COST}" "0.004800" "t9a: sonnet-5 at \$2/M in + \$10/M out"
assert_eq "${LOGGED_MODEL}" "claude-sonnet-5" "t9a: model id in cost.log"
cost_for opus "{\"default_model\": \"claude-opus-4-8\", ${PRICES}}" 1200 240
assert_eq "${COST}" "0.012000" "t9b: opus-4-8 at \$5/M in + \$25/M out"
assert_eq "$(json_get "${S_FAKE}/messages-1.request.json" "d['model']")" "claude-opus-4-8" "t9b: the request carries the configured model"
cost_for haiku '{"default_model": "claude-haiku-4-5", "cost_pricing": {"claude-sonnet-5": {"input_per_million": 2, "output_per_million": 10}}}' 1200 240
assert_eq "${COST}" "0.004800" "t9c: unpriced model falls back to sonnet-5 rates"
assert_contains "${ERR}" "no cost_pricing for model claude-haiku-4-5" "t9c: warns about the fallback"
# Cache writes bill at 1.25x input, cache reads at 0.1x:
#   (200*2 + 1000*2*1.25 + 4000*2*0.1 + 240*10) / 1e6 = 0.006100
cost_for cache "{\"default_model\": \"claude-sonnet-5\", ${PRICES}}" 200 240 1000 4000
assert_eq "${COST}" "0.006100" "t9d: cache write and read terms are billed"
assert_eq "${LOGGED_IN}" "5200" "t9d: cost.log input column counts cached tokens"

# ---------------------------------------------------------------------
# Test 10 - the machinery this design removed is gone.
# ---------------------------------------------------------------------
GONE="$(cd "${MODULE_ROOT}" && grep -rniE 'calibrat|REJECT_GIVEUP|rejected-days|rejected_count_for_day|analyzer_version|hold_day_for_failure|char_total|// ?4\b' bin/autoheal-analyze.sh lib/analyzer-prompt.md lib/draft_proposals.py lib/proposal-schema.json || true)"
assert_eq "${GONE}" "" "t10: no calibration, SHA counter, rejected-day hold or chars/4 estimate"
assert_not_contains "$(cat "${MODULE_ROOT}/bin/autoheal-analyze.sh")" "max_input_tokens" "t10: the config max_input_tokens cap is not read"

echo ""
echo "test-analyzer-api-call.sh: ${PASS} passed, ${FAIL} failed"
[ "${FAIL}" -eq 0 ]
