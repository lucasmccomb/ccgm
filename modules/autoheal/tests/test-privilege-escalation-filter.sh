#!/usr/bin/env bash
# The model's answer is untrusted: it can only reach a file and a heading the
# code already vetted. This test pins the checks lib/draft_proposals.py
# `finish` runs between the model's answer and a proposal row. It replaced
# the breadth/confidence privilege gate, which guarded a free-form proposal
# the model no longer writes (#1099 Phase 2.2).
#
# Each case feeds `finish` one answer and expects either a row or a counted
# drop reason, and checks that a dropped answer leaves no proposal behind.

set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MODULE_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
# shellcheck source=analyzer-fixture.sh
. "${SCRIPT_DIR}/analyzer-fixture.sh"

PASS=0
FAIL=0
TODAY="2026-10-04"
ROOT=$(mktemp -d -t autoheal_gate.XXXXXX)
trap 'rm -rf "${ROOT}"' EXIT

REPO="${ROOT}/repo"
fx_repo "${REPO}"
CQ="modules/code-quality/rules/code-quality.md"
GW="modules/git-workflow/rules/git-workflow.md"

# finish_case <name> <answer json>: run finish with candidates = code-quality only.
finish_case() {
    CASE="${ROOT}/$1"
    mkdir -p "${CASE}/ah"
    python3 - "${CASE}/meta.json" "${REPO}" <<'PY'
import json, sys
json.dump({
    "signature_id": "abc123def456", "model": "claude-sonnet-5", "repo_root": sys.argv[2],
    "candidates": ["modules/code-quality/rules/code-quality.md"],
    "signature": {"signature_id": "abc123def456", "tool_name": "Bash", "cmd_head": "echo",
                  "error_class": "zsh_not_found", "count": 12, "sessions": 3, "repos": 1, "days": 2,
                  "first_seen": "2026-10-03", "last_seen": "2026-10-04", "calls": 500,
                  "rate_per_100_calls": 2.4, "samples": ["(eval):1: ==== not found"]},
}, open(sys.argv[1], "w"))
PY
    printf '%s' "$2" > "${CASE}/answer.json"
    RESULT="$(CCGM_AUTOHEAL_DIR="${CASE}/ah" CCGM_AUTOHEAL_TODAY="${TODAY}" \
        python3 "${MODULE_ROOT}/lib/draft_proposals.py" finish --meta "${CASE}/meta.json" \
        --answer "${CASE}/answer.json" --date "${TODAY}" --rejected-log "${CASE}/rejected.log" 2>&1)"
    ROWS="${CASE}/ah/proposals.jsonl"
}
rule_insert() {
    python3 -c "
import json, sys
print(json.dumps({'proposal': {'kind': 'rule_insert', 'target_path': sys.argv[1], 'anchor_heading': sys.argv[2], 'insert_markdown': sys.argv[3]}}))" "$@"
}
dropped_with() {
    assert_contains "${RESULT}" "\"reason\": \"$2\"" "$1: dropped as $2"
    assert_eq "$(jsonl_get "${ROWS}" 1 "d['state'] + ' ' + d['drop_reason']")" "dropped $2" "$1: stored as dropped, never ready"
    assert_contains "$(cat "${CASE}/rejected.log")" "$2" "$1: reason in the rejection log"
}

# A compliant answer is accepted.
finish_case ok "$(rule_insert "${CQ}" "Code Standards" "- Quote glob flags under zsh.")"
assert_contains "${RESULT}" '"outcome": "rule_insert"' "ok: accepted"
assert_eq "$(jsonl_get "${ROWS}" 1 "d['id']")" "abc123def456" "ok: id comes from the signature, not the model"

# The model cannot write outside the candidate set, even to a real file.
finish_case other_real_file "$(rule_insert "${GW}" "Never Stash" "- x")"
dropped_with other_real_file path_not_candidate
finish_case invented_file "$(rule_insert "modules/invented/rules/made-up.md" "Anything" "- x")"
dropped_with invented_file path_not_candidate
finish_case traversal "$(rule_insert "../../etc/hosts" "Anything" "- x")"
dropped_with traversal path_not_candidate
finish_case absolute "$(rule_insert "${REPO}/${CQ}" "Code Standards" "- x")"
dropped_with absolute path_not_candidate

# The anchor must be a real heading of that file. Text outside headings and
# headings inside code fences do not count.
finish_case anchor "$(rule_insert "${CQ}" "No Such Heading" "- x")"
dropped_with anchor anchor_missing
finish_case anchor_body_text "$(rule_insert "${CQ}" "Choose the simplest implementation that fully meets the requirements." "- x")"
dropped_with anchor_body_text anchor_missing
finish_case anchor_hashes "$(rule_insert "${CQ}" "## Code Standards" "- x")"
assert_contains "${RESULT}" '"outcome": "rule_insert"' "anchor_hashes: a leading ## on the anchor is tolerated"

# Length limits.
finish_case long "$(rule_insert "${CQ}" "Code Standards" "$(printf 'line\n%.0s' 1 2 3 4 5 6 7 8 9)")"
dropped_with long insert_too_long
finish_case eight "$(rule_insert "${CQ}" "Code Standards" "$(printf 'line\n%.0s' 1 2 3 4 5 6 7 8)")"
assert_contains "${RESULT}" '"outcome": "rule_insert"' "eight: 8 lines is allowed"
finish_case empty "$(rule_insert "${CQ}" "Code Standards" "  ")"
dropped_with empty insert_empty

# Shape errors.
finish_case notjson "this is not json"
dropped_with notjson answer_not_json
finish_case wrongkind '{"proposal": {"kind": "settings_allow_add", "id": "x"}}'
dropped_with wrongkind answer_malformed
finish_case flat '{"kind": "rule_insert", "target_path": "x"}'
dropped_with flat answer_malformed
finish_case diffonly '{"proposal": {"kind": "rule_insert", "target_path": "modules/code-quality/rules/code-quality.md", "anchor_heading": "Code Standards"}}'
dropped_with diffonly answer_malformed

# Whatever extra the model sends (a diff, an id) never reaches the row.
finish_case extras '{"proposal": {"kind": "rule_insert", "target_path": "modules/code-quality/rules/code-quality.md", "anchor_heading": "Code Standards", "insert_markdown": "- x", "id": "evil", "proposed_diff": "rm -rf /", "diff": "bogus"}}'
assert_eq "$(jsonl_get "${ROWS}" 1 "d['id']")" "abc123def456" "extras: a model-supplied id is ignored"
assert_not_contains "$(cat "${ROWS}")" "rm -rf" "extras: a model-supplied diff is ignored"

echo ""
echo "test-privilege-escalation-filter.sh: ${PASS} passed, ${FAIL} failed"
[ "${FAIL}" -eq 0 ]
