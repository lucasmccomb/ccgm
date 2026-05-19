#!/usr/bin/env bash
# Test suite for the /autoheal-apply slash command spec.
#
# The command itself is documented in modules/autoheal/commands/autoheal-apply.md
# and is implemented in two halves:
#
#   - LIST mode: agent-driven read of past-7-days proposals files, skipping
#     applied + snoozed. There is no executable for list mode; the agent
#     follows the documented procedure. This test exercises the SAME read
#     logic the agent should use, so a future implementation in code (e.g.
#     a small `autoheal-apply-list.py`) can be wired without changing the
#     contract.
#
#   - APPLY mode: routes through lib/apply-proposal.py — the gate test
#     (test-auto-apply-gate.sh) covers that path end-to-end. This test
#     only spot-checks that the CLI exposes the documented usage.
#
# Run: bash modules/autoheal/tests/test-autoheal-apply-command.sh

set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MODULE_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
APPLY_LIB="${MODULE_ROOT}/lib/apply-proposal.py"
COMMAND_DOC="${MODULE_ROOT}/commands/autoheal-apply.md"

PASS=0
FAIL=0

assert_eq() {
    local actual="$1"
    local expected="$2"
    local label="$3"
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
    local haystack="$1"
    local needle="$2"
    local label="$3"
    case "${haystack}" in
        *"${needle}"*)
            PASS=$((PASS + 1))
            ;;
        *)
            FAIL=$((FAIL + 1))
            echo "FAIL: ${label}"
            echo "  expected substring: ${needle}"
            echo "  actual: ${haystack}"
            ;;
    esac
}

# ---------------------------------------------------------------------
# Test 1: the command doc names the expected subcommands. A regression
# in the command surface would silently break the agent that follows the
# spec, so we pin the wording.
# ---------------------------------------------------------------------

[ -f "${COMMAND_DOC}" ] && PASS=$((PASS + 1)) || {
    FAIL=$((FAIL + 1))
    echo "FAIL: command doc exists at ${COMMAND_DOC}"
}

doc_content=$(cat "${COMMAND_DOC}" 2>/dev/null || echo "")
assert_contains "${doc_content}" "/autoheal-apply" \
    "doc: top-level command name present"
assert_contains "${doc_content}" "/autoheal-apply list" \
    "doc: list subcommand documented"
assert_contains "${doc_content}" "/autoheal-apply <proposal-id>" \
    "doc: apply-by-id subcommand documented"
assert_contains "${doc_content}" "lib/apply-proposal.py" \
    "doc: routes through the shared apply library"
assert_contains "${doc_content}" "autoheal/{proposal-id}" \
    "doc: names the manual-apply branch shape"
assert_contains "${doc_content}" "tests/test-modules.sh" \
    "doc: test-gate references test-modules.sh"
assert_contains "${doc_content}" "tests/test-no-personal-data.sh" \
    "doc: test-gate references test-no-personal-data.sh"

# ---------------------------------------------------------------------
# Test 2: the CLI exposes the documented usage string and rejects bad
# source labels. We do not run the apply itself here (the gate test
# covers that); we only confirm the CLI surface matches the doc.
# ---------------------------------------------------------------------

usage=$(python3 "${APPLY_LIB}" 2>&1 || true)
assert_contains "${usage}" "apply-proposal.py" "cli: usage names the script"
assert_contains "${usage}" "permission-fix|auto-apply" \
    "cli: usage names the two source labels"

bad_source=$(python3 "${APPLY_LIB}" prop_x notarealsource 2>&1 || true)
assert_contains "${bad_source}" "source must be" \
    "cli: rejects unknown source labels"

# ---------------------------------------------------------------------
# Test 3: LIST mode logic — read the last N days, skip applied, skip
# future-snoozed. We do not run a list executable (the command is
# agent-driven); we exercise the procedure the agent should follow.
# ---------------------------------------------------------------------

PROPOSALS_DIR="$(mktemp -d -t autoheal_list_proposals.XXXXXX)"
APPLIED_DIR="$(mktemp -d -t autoheal_list_applied.XXXXXX)"
trap 'rm -rf "${PROPOSALS_DIR}" "${APPLIED_DIR}"' EXIT

TODAY="2026-05-18"
YDAY="2026-05-17"

# Today: 3 proposals (1 normal, 1 future-snoozed, 1 already-applied).
cat > "${PROPOSALS_DIR}/${TODAY}.jsonl" <<EOF
{"id":"prop_today_a","kind":"settings_allow_add","title":"add A","confidence":9,"breadth_score":1,"occurrence_count":2,"session_ids":["s1"],"proposed_diff_target":"modules/settings/x","proposed_diff":"","fingerprint":"fa","originating_clone":"c","generated_at":"${TODAY}T00:00:00Z"}
{"id":"prop_today_b","kind":"settings_allow_add","title":"add B","confidence":9,"breadth_score":1,"occurrence_count":2,"session_ids":["s1"],"proposed_diff_target":"modules/settings/x","proposed_diff":"","fingerprint":"fb","originating_clone":"c","generated_at":"${TODAY}T00:00:00Z","snoozed_until":"2099-01-01T00:00:00Z"}
{"id":"prop_today_c","kind":"settings_allow_add","title":"add C","confidence":9,"breadth_score":1,"occurrence_count":2,"session_ids":["s1"],"proposed_diff_target":"modules/settings/x","proposed_diff":"","fingerprint":"fc","originating_clone":"c","generated_at":"${TODAY}T00:00:00Z"}
EOF

# Yesterday: 1 proposal (still pending).
cat > "${PROPOSALS_DIR}/${YDAY}.jsonl" <<EOF
{"id":"prop_yday_a","kind":"hook_narrow","title":"narrow X","confidence":7,"breadth_score":3,"occurrence_count":2,"session_ids":["s1"],"proposed_diff_target":"modules/hooks/x","proposed_diff":"","fingerprint":"fy","originating_clone":"c","generated_at":"${YDAY}T00:00:00Z"}
EOF

# Mark prop_today_c as already applied.
cat > "${APPLIED_DIR}/${TODAY}.jsonl" <<EOF
{"id":"app_prop_today_c","ts":"${TODAY}T01:00:00Z","proposal_id":"prop_today_c","method":"permission_fix","branch":"autoheal/prop_today_c","commit_sha":"abc","tests_passed":true,"rolled_back":false}
EOF

# The agent's list procedure:
#   1. Walk proposals_dir for the last 8 days.
#   2. Skip any whose snoozed_until is in the future (vs TODAY).
#   3. Skip any whose id is present in applied_dir/*.jsonl.
#   4. Emit a sorted table.
list_output=$(
    CCGM_AUTOHEAL_PROPOSALS_DIR="${PROPOSALS_DIR}" \
    CCGM_AUTOHEAL_APPLIED_DIR="${APPLIED_DIR}" \
    CCGM_AUTOHEAL_TODAY="${TODAY}" \
    python3 - <<'PY'
import datetime as dt
import glob
import json
import os

prop_dir = os.environ["CCGM_AUTOHEAL_PROPOSALS_DIR"]
appl_dir = os.environ["CCGM_AUTOHEAL_APPLIED_DIR"]
today_iso = os.environ["CCGM_AUTOHEAL_TODAY"]
today = dt.date.fromisoformat(today_iso)

# Applied id set.
applied = set()
for path in glob.glob(os.path.join(appl_dir, "*.jsonl")):
    with open(path) as fh:
        for line in fh:
            try:
                rec = json.loads(line)
            except (json.JSONDecodeError, ValueError):
                continue
            pid = rec.get("proposal_id") or rec.get("id")
            if pid:
                applied.add(pid)

now_iso = today_iso + "T23:59:59Z"

pending = []
for offset in range(0, 8):
    day = (today - dt.timedelta(days=offset)).isoformat()
    path = os.path.join(prop_dir, f"{day}.jsonl")
    if not os.path.isfile(path):
        continue
    with open(path) as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except (json.JSONDecodeError, ValueError):
                continue
            pid = rec.get("id")
            if not pid or pid in applied:
                continue
            snz = rec.get("snoozed_until")
            if snz and snz > now_iso:
                continue
            pending.append(rec)

pending.sort(
    key=lambda r: (
        -int(r.get("confidence") or 0),
        int(r.get("breadth_score") or 99),
        r.get("generated_at") or "",
    )
)

for rec in pending:
    print(
        f"{rec['id']}\t{rec['kind']}\t{rec.get('confidence', '-')}/10\t"
        f"{rec.get('breadth_score', '-')}\t{rec.get('title', '')}"
    )

print(f"--PENDING={len(pending)}")
PY
)

assert_contains "${list_output}" "prop_today_a" \
    "list: pending today proposal appears"
assert_contains "${list_output}" "prop_yday_a"  \
    "list: pending yesterday proposal appears"
# prop_today_b is snoozed — must be skipped.
case "${list_output}" in
    *prop_today_b*)
        FAIL=$((FAIL + 1))
        echo "FAIL: list: snoozed proposal must be skipped"
        ;;
    *)
        PASS=$((PASS + 1))
        ;;
esac
# prop_today_c is already applied — must be skipped.
case "${list_output}" in
    *prop_today_c*)
        FAIL=$((FAIL + 1))
        echo "FAIL: list: already-applied proposal must be skipped"
        ;;
    *)
        PASS=$((PASS + 1))
        ;;
esac
assert_contains "${list_output}" "--PENDING=2" \
    "list: pending count = 2"

echo ""
echo "test-autoheal-apply-command.sh: ${PASS} passed, ${FAIL} failed"
[ "${FAIL}" -eq 0 ] || exit 1
exit 0
