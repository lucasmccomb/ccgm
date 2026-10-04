#!/usr/bin/env bash
# Tests for the redraft cooldown (#1099 Phase 2.3 follow-up): a signature whose
# draft was dropped must not be drafted, and paid for, again every night.
#
#   content drop (personal_data, ...)  -> redraft_cooldown_days (14) from the drop
#   each further content drop          -> the cooldown doubles, capped at 90
#   validation_unavailable             -> 1 day; three in a row -> 14 days
#   model skip                         -> covered with no expiry
# Plus the end-to-end case: a dropped draft is stored, and the next night makes
# zero API calls.

set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MODULE_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
ANALYZER="${MODULE_ROOT}/bin/autoheal-analyze.sh"
AGGREGATE="${MODULE_ROOT}/bin/autoheal-aggregate.py"
# shellcheck source=analyzer-fixture.sh
. "${SCRIPT_DIR}/analyzer-fixture.sh"

PASS=0
FAIL=0
TODAY="2026-10-04"
ROOT=$(mktemp -d -t autoheal_cooldown.XXXXXX)
trap 'rm -rf "${ROOT}"' EXIT

BAD_ANCHOR='{"proposal":{"kind":"rule_insert","target_path":"modules/code-quality/rules/code-quality.md","anchor_heading":"No Such Heading","insert_markdown":"- x"}}'

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
    fx_events "${S_AH}" "${TODAY}" Bash echo zsh_not_found "(eval):1: ==== not found" 12 3
    SIG_ID="$(sig_state | cut -f1)"
}

# aggregate: run the aggregator for TODAY in the scenario.
aggregate() {
    env CCGM_AUTOHEAL_DIR="${S_AH}" python3 "${AGGREGATE}" --date "${TODAY}" > /dev/null
}

# sig_state: "<id>\t<qualifies>\t<excluded>\t<cooldown_until>" for the one signature.
sig_state() {
    aggregate
    python3 -c "
import json, sys
s = json.load(open(sys.argv[1]))['signatures'][0]
print('\t'.join([s['signature_id'], str(s['qualifies']), s.get('excluded', '-'), s.get('cooldown_until', '-')]))
" "${S_AH}/signatures/${TODAY}.json"
}

# seed <days ago> <state> <reason>: a ledger row for the signature, dated that many days back.
seed() {
    python3 - "${S_AH}" "${SIG_ID}" "$1" "$2" "$3" "${TODAY}" <<'PY'
import datetime as dt, json, os, sys
ah, sid, ago, state, reason, today = sys.argv[1:7]
day = dt.date.fromisoformat(today) - dt.timedelta(days=int(ago))
os.makedirs(ah, exist_ok=True)
row = {"id": sid, "signature_id": sid, "state": state, "kind": "rule_insert",
       "generated_at": day.isoformat() + "T12:00:00+00:00"}
if reason != "-":
    row["drop_reason"] = reason
with open(ah + "/proposals.jsonl", "a") as fh:
    fh.write(json.dumps(row) + "\n")
PY
}

# field <n> of sig_state output
field() { printf '%s' "$1" | cut -f"$2"; }

run_analyzer() {
    env HOME="${S_HOME}" PATH="${S_BIN}:${PATH}" FAKE_CURL_DIR="${S_FAKE}" \
        CCGM_AUTOHEAL_DIR="${S_AH}" CCGM_AUTOHEAL_TODAY="${TODAY}" \
        CCGM_AUTOHEAL_CLONE_ID="ccgm-w1-c0" ANTHROPIC_API_KEY="sk-test-not-real" \
        "$@" bash "${ANALYZER}" >"${S_ROOT}/run.out" 2>"${S_ROOT}/run.err"
    RC=$?
    ERR="$(cat "${S_ROOT}/run.err")"
}

# 1. Dropped as personal_data yesterday: in cooldown today.
scenario c1
seed 1 dropped personal_data
ST="$(sig_state)"
assert_eq "$(field "${ST}" 2)" "False" "dropped yesterday: does not qualify"
assert_eq "$(field "${ST}" 3)" "cooldown" "dropped yesterday: excluded as cooldown"
assert_eq "$(field "${ST}" 4)" "2026-10-17" "dropped yesterday: cooldown_until is drop date + 14"

# 2. The cooldown ends after 14 days.
scenario c2
seed 14 dropped personal_data
ST="$(sig_state)"
assert_eq "$(field "${ST}" 2)" "True" "dropped 14 days ago: qualifies again"
scenario c2b
seed 13 dropped personal_data
assert_eq "$(field "$(sig_state)" 3)" "cooldown" "dropped 13 days ago: still cooling down"

# 3. A second content drop doubles it to 28 days.
scenario c3
seed 30 dropped personal_data
seed 20 dropped module_tests
ST="$(sig_state)"
assert_eq "$(field "${ST}" 3)" "cooldown" "second drop: 20 days after is still inside 28"
assert_eq "$(field "${ST}" 4)" "2026-10-12" "second drop: cooldown_until is last drop + 28"

# 4. The cooldown caps at 90 days.
scenario c4
for ago in 400 300 200 100 50 1; do seed "${ago}" dropped anchor_missing; done
assert_eq "$(field "$(sig_state)" 4)" "2027-01-01" "six drops: cooldown capped at 90 days"

# 5. validation_unavailable yesterday: retry tonight.
scenario c5
seed 1 dropped validation_unavailable
ST="$(sig_state)"
assert_eq "$(field "${ST}" 2)" "True" "validation_unavailable yesterday: qualifies today"
scenario c5b
seed 0 dropped validation_unavailable
assert_eq "$(field "$(sig_state)" 3)" "cooldown" "validation_unavailable today: not retried the same day"

# 6. Three in a row start the 14-day cooldown; two do not.
scenario c6
seed 3 dropped validation_unavailable
seed 2 dropped validation_unavailable
assert_eq "$(field "$(sig_state)" 2)" "True" "two validation_unavailable drops: still retried"
seed 1 dropped validation_unavailable
ST="$(sig_state)"
assert_eq "$(field "${ST}" 3)" "cooldown" "three validation_unavailable drops: cooldown"
assert_eq "$(field "${ST}" 4)" "2026-10-17" "three validation_unavailable drops: 14 days from the last"

# 7. A content drop between infra drops breaks the run.
scenario c7
seed 4 dropped validation_unavailable
seed 3 dropped validation_unavailable
seed 2 dropped personal_data
seed 1 dropped validation_unavailable
assert_eq "$(field "$(sig_state)" 2)" "True" "infra run broken by a content drop: one day only"

# 8. The config key sets the base.
scenario c8
printf '{"aggregation": {"redraft_cooldown_days": 3}}\n' > "${S_AH}/config.json"
seed 3 dropped personal_data
assert_eq "$(field "$(sig_state)" 2)" "True" "redraft_cooldown_days=3: qualifies after 3 days"

# 9. A skip covers the signature with no expiry.
scenario c9
seed 200 skipped -
ST="$(sig_state)"
assert_eq "$(field "${ST}" 2)" "False" "skip 200 days ago: still covered"
assert_eq "$(field "${ST}" 3)" "covered" "skip: excluded as covered"

# 10. End to end: a draft dropped by the model's bad anchor is stored, and the next
#     night makes no API call.
scenario c10
fx_answer "${S_FAKE}/messages.response.json" "${BAD_ANCHOR}"
echo '{"input_tokens": 9000}' > "${S_FAKE}/count_tokens.response.json"
run_analyzer
assert_eq "$(fx_calls "${S_FAKE}" messages)" "1" "e2e: night one drafts once"
assert_contains "${ERR}" "anchor_missing" "e2e: the drop is logged with its reason"
ROW="$(python3 -c "
import json, sys
r = json.loads(open(sys.argv[1]).readline()); print(r['state'], r['drop_reason'])
" "${S_AH}/proposals.jsonl")"
assert_eq "${ROW}" "dropped anchor_missing" "e2e: the dropped draft is stored"
rm -f "${S_FAKE}/calls.log"
run_analyzer
assert_eq "$(fx_calls "${S_FAKE}" messages)" "0" "e2e: night two makes zero messages calls"
assert_eq "$(fx_calls "${S_FAKE}" count_tokens)" "0" "e2e: night two makes zero count_tokens calls"
assert_contains "${ERR}" "no qualifying" "e2e: night two logs that nothing qualifies"

# 11. Three validation_unavailable drops record the streak on the row for the health writer.
scenario c11
git -C "${S_REPO}" update-ref -d refs/remotes/origin/main
python3 - "${S_ROOT}" "${S_REPO}" "${SIG_ID}" <<'PY'
import json, sys
root, repo, sid = sys.argv[1:4]
sig = {"signature_id": sid, "tool_name": "Bash", "cmd_head": "echo", "error_class": "zsh_not_found", "count": 12, "sessions": 3, "days": 2}
json.dump({"signature_id": sid, "signature": sig, "candidates": ["modules/code-quality/rules/code-quality.md"],
           "repo_root": repo, "model": "m"}, open(root + "/meta.json", "w"))
json.dump({"proposal": {"kind": "rule_insert", "target_path": "modules/code-quality/rules/code-quality.md",
                        "anchor_heading": "Testing", "insert_markdown": "- fine"}}, open(root + "/answer.json", "w"))
PY
for _ in 1 2 3; do
    env CCGM_AUTOHEAL_DIR="${S_AH}" CCGM_AUTOHEAL_TODAY="${TODAY}" python3 "${MODULE_ROOT}/lib/draft_proposals.py" finish \
        --meta "${S_ROOT}/meta.json" --answer "${S_ROOT}/answer.json" --date "${TODAY}" > /dev/null
done
STREAK="$(python3 -c "
import json, sys
rows = [json.loads(l) for l in open(sys.argv[1])]
print([r['consecutive_unavailable'] for r in rows], 'health_reason' in rows[1], 'health_reason' in rows[2])
" "${S_AH}/proposals.jsonl")"
assert_eq "${STREAK}" "[1, 2, 3] False True" "streak is recorded on each row; health_reason appears at three"

echo ""
echo "test-redraft-cooldown.sh: ${PASS} passed, ${FAIL} failed"
[ "${FAIL}" -eq 0 ]
