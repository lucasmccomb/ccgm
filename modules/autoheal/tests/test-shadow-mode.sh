#!/usr/bin/env bash
# test-shadow-mode.sh (#1087)
#
# autoheal's auto_apply_enabled and realtime_alerts_enabled take
# off | shadow | active. In shadow the decision is computed and logged and
# nothing else happens. Verifies:
#   1. autoheal_mode.resolve_mode: persisted booleans read as active/off,
#      strings pass through, anything else fails closed to off.
#   2. agreement(): agree, false positive, false negative, pending; guarded
#      (check-surface) false positives; latest decision per proposal wins.
#   3. promotion_verdict(): the named-constant bar (20 decided, 90%, zero
#      guarded false positives).
#   4. autoheal-auto-apply.sh in shadow: logs would_apply with a reason, never
#      creates a branch or an applied record; check-surface proposals are
#      would_apply=false; active mode still applies.
#   5. realtime-security-scanner.py in shadow: logs would_alert, emits no
#      <autoheal-security-alert> block, exits 0; active mode still alerts.
#   6. autoheal-digest.sh shows the shadow counts and promotion status.
#   7. The toggle (autoheal_mode.py set) writes shadow, on/off, and rejects
#      junk, preserving other keys.
#
# Run: bash modules/autoheal/tests/test-shadow-mode.sh

set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MODULE_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
REPO_ROOT="$(cd "${MODULE_ROOT}/../.." && pwd)"
LIB="${MODULE_ROOT}/lib"
MODE_PY="${LIB}/autoheal_mode.py"
AUTO_APPLY_SH="${MODULE_ROOT}/bin/autoheal-auto-apply.sh"
DIGEST_SH="${MODULE_ROOT}/bin/autoheal-digest.sh"
HOOK="${MODULE_ROOT}/hooks/realtime-security-scanner.py"
SCENARIOS="${SCRIPT_DIR}/fixtures/eval-scenarios.json"

PASS=0
FAIL=0
TMPROOT="$(mktemp -d -t autoheal-shadow.XXXXXX)"
trap 'rm -rf "${TMPROOT}"' EXIT

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
assert_contains() {
    case "$1" in
        *"$2"*) PASS=$((PASS + 1)) ;;
        *)
            FAIL=$((FAIL + 1))
            echo "FAIL: $3"
            echo "  missing: $2"
            echo "  in (first 600): ${1:0:600}"
            ;;
    esac
}
assert_not_contains() {
    case "$1" in
        *"$2"*)
            FAIL=$((FAIL + 1))
            echo "FAIL: $3"
            echo "  unexpectedly present: $2"
            ;;
        *) PASS=$((PASS + 1)) ;;
    esac
}

py() { PYTHONPATH="${LIB}" python3 "$@"; }

# --- 1. resolver -------------------------------------------------------
out="$(py - <<'PY'
import autoheal_mode as m
r = m.resolve_mode
print(r(True), r(False), r(None), r("off"), r("shadow"), r("active"), r(" Shadow "))
print(r("on"), r("true"), r(1), r(0), r([]), r({}))
PY
)"
assert_eq "$(printf '%s\n' "${out}" | sed -n 1p)" "active off off off shadow active shadow" "resolve: booleans and strings"
assert_eq "$(printf '%s\n' "${out}" | sed -n 2p)" "off off off off off off" "resolve: unrecognised values fail closed"

mkdir -p "${TMPROOT}/cfg"
echo '{"auto_apply_enabled": true, "realtime_alerts_enabled": "shadow"}' > "${TMPROOT}/cfg/a.json"
echo 'not json' > "${TMPROOT}/cfg/bad.json"
out="$(py - "${TMPROOT}" <<'PY'
import sys, autoheal_mode as m
d = sys.argv[1] + "/cfg/"
print(m.read_mode(d + "a.json", "auto_apply_enabled"),
      m.read_mode(d + "a.json", "realtime_alerts_enabled"),
      m.read_mode(d + "a.json", "missing_key"),
      m.read_mode(d + "bad.json", "auto_apply_enabled"),
      m.read_mode(d + "nope.json", "auto_apply_enabled"))
PY
)"
assert_eq "${out}" "active shadow off off off" "read_mode: true->active, string passthrough, missing/bad/absent -> off"
assert_eq "$(py "${MODE_PY}" mode "${TMPROOT}/cfg/a.json" auto_apply_enabled)" "active" "CLI mode prints the resolved mode"

# --- 2. agreement ------------------------------------------------------
out="$(py - <<'PY'
import autoheal_mode as m
d = lambda pid, would, surface="rule", fp=None: {"proposal_id": pid, "would_apply": would, "fix_surface": surface, "fingerprint": fp or "fp-" + pid}
decisions = [d("agree-yes", True), d("agree-no", False), d("fp", True), d("fn", False), d("pend", True),
             d("fp-check", True, "check")]
outcomes = {"agree-yes": "accepted", "agree-no": "rejected", "fp": "rejected", "fn": "accepted", "fp-check": "rejected"}
s = m.agreement(decisions, outcomes)
print(s["decisions"], s["agreed"], s["false_positives"], s["false_negatives"], s["pending"], s["guarded_false_positives"])
s = m.agreement([d("p", False), d("p", True)], {"p": "accepted"})
print(s["decisions"], s["agreed"])
# human_outcomes: applied -> accepted, snoozed fingerprint -> rejected, applied wins
oc = m.human_outcomes([d("a", True), d("b", True), d("c", True), d("e", True, fp="fp-both")],
                      applied_ids={"a", "e"}, snoozed_fingerprints={"fp-b", "fp-both"})
print(oc.get("a"), oc.get("b"), oc.get("c"), oc.get("e"))
PY
)"
assert_eq "$(printf '%s\n' "${out}" | sed -n 1p)" "6 2 2 1 1 1" "agreement: counts per cell, pending, guarded false positive"
assert_eq "$(printf '%s\n' "${out}" | sed -n 2p)" "1 1" "agreement: latest record per proposal wins"
assert_eq "$(printf '%s\n' "${out}" | sed -n 3p)" "accepted rejected None accepted" "human_outcomes: applied, snoozed, none; applied wins over snooze"

# --- 3. promotion bar --------------------------------------------------
out="$(py - <<'PY'
import autoheal_mode as m
def s(agreed, fp=0, fn=0, guarded=0, pending=0):
    return {"decisions": agreed + fp + fn + pending, "agreed": agreed, "false_positives": fp,
            "false_negatives": fn, "pending": pending, "guarded_false_positives": guarded}
v = m.promotion_verdict
print(m.PROMOTION_MIN_DECIDED, m.PROMOTION_MIN_AGREEMENT, m.PROMOTION_MAX_GUARDED_FALSE_POSITIVES)
print(v(s(18, fn=2))["ready"], v(s(19))["ready"], v(s(17, fn=3))["ready"],
      v(s(29, fp=1, guarded=1))["ready"], v(s(10, pending=50))["ready"])
PY
)"
assert_eq "$(printf '%s\n' "${out}" | sed -n 1p)" "20 0.9 0" "promotion: documented constants"
assert_eq "$(printf '%s\n' "${out}" | sed -n 2p)" "True False False False False" "promotion: met at the bar; short, low agreement, guarded FP, pending-only all fail"

# --- 4. auto-apply shadow ---------------------------------------------
CLONE="${TMPROOT}/clone"
mkdir -p "${CLONE}/tests" "${CLONE}/modules/settings"
touch "${CLONE}/start.sh"
printf '#!/usr/bin/env bash\nexit 0\n' > "${CLONE}/tests/test-modules.sh"
printf '#!/usr/bin/env bash\nexit 0\n' > "${CLONE}/tests/test-no-personal-data.sh"
cat > "${CLONE}/modules/settings/settings.partial.json" <<'EOF'
{
  "permissions": {
    "allow": [
      "Bash(git status)"
    ]
  }
}
EOF
(
    cd "${CLONE}"
    git init -q -b main
    git config user.email "test@example.invalid"
    git config user.name "test"
    git config commit.gpgsign false
    git config core.hooksPath "${CLONE}/.git/empty-hooks"
    mkdir -p "${CLONE}/.git/empty-hooks"
    git add -A
    git commit -q -m init
)

TODAY="2026-06-14"
PROPS="${TMPROOT}/props"
mkdir -p "${PROPS}"
python3 - "${PROPS}/${TODAY}.jsonl" <<'PY'
import json, sys
diff = lambda rule: (
    "--- a/modules/settings/settings.partial.json\n+++ b/modules/settings/settings.partial.json\n"
    "@@ -1,5 +1,6 @@\n {\n   \"permissions\": {\n     \"allow\": [\n"
    "-      \"Bash(git status)\"\n+      \"Bash(git status)\",\n+      \"" + rule + "\"\n     ]\n   }\n }\n")
base = {"kind": "settings_allow_add", "title": "t", "rationale": "r", "confidence": 9, "breadth_score": 1,
        "occurrence_count": 3, "session_ids": ["s1", "s2"],
        "proposed_diff_target": "modules/settings/settings.partial.json",
        "originating_clone": "c", "generated_at": "2026-06-14T00:00:00Z"}
recs = [
    {**base, "id": "prop_good", "fingerprint": "fp-good", "fix_surface": "rule", "proposed_diff": diff("Bash(git diff)")},
    {**base, "id": "prop_regress", "fingerprint": "fp-regress", "fix_surface": "rule", "proposed_diff": diff("Bash(git:*)")},
    {**base, "id": "prop_check", "fingerprint": "fp-check", "fix_surface": "check", "proposed_diff": diff("Bash(git diff)")},
    {**base, "id": "prop_lowconf", "fingerprint": "fp-low", "fix_surface": "rule", "confidence": 5,
     "proposed_diff": diff("Bash(git diff)")},
    {**base, "id": "prop_legacy", "fingerprint": "fp-legacy", "proposed_diff": diff("Bash(git diff)")},
]
with open(sys.argv[1], "w") as fh:
    for r in recs:
        fh.write(json.dumps(r) + "\n")
PY

run_auto_apply() {
    # Args: config-json.
    local cfg="${TMPROOT}/auto-config.json"
    printf '%s\n' "$1" > "${cfg}"
    rm -rf "${TMPROOT}/applied" "${TMPROOT}/shadow" "${TMPROOT}/logs"
    CCGM_AUTOHEAL_CONFIG="${cfg}" \
    CCGM_AUTOHEAL_PROPOSALS_DIR="${PROPS}" \
    CCGM_AUTOHEAL_APPLIED_DIR="${TMPROOT}/applied" \
    CCGM_AUTOHEAL_SHADOW_DIR="${TMPROOT}/shadow" \
    CCGM_AUTOHEAL_LOGS_DIR="${TMPROOT}/logs" \
    CCGM_AUTOHEAL_TODAY="${TODAY}" \
    CCGM_AUTOHEAL_CLONE_ROOT="${CLONE}" \
    CCGM_AUTOHEAL_EVAL_SCENARIOS="${SCENARIOS}" \
    bash "${AUTO_APPLY_SH}" 2>&1
}

out="$(run_auto_apply '{"auto_apply_enabled": "shadow"}')"
assert_eq "$(cd "${CLONE}" && git branch --list 'autoheal/auto/*')" "" "shadow auto-apply: no branch created"
assert_eq "$(cd "${CLONE}" && git rev-parse --abbrev-ref HEAD)" "main" "shadow auto-apply: clone stays on main"
assert_eq "$(ls "${TMPROOT}/applied" 2>/dev/null | wc -l | tr -d ' ')" "0" "shadow auto-apply: no applied record"
assert_contains "${out}" "shadow" "shadow auto-apply: summary names shadow mode"
SHADOW_LOG="${TMPROOT}/shadow/auto-apply.jsonl"
get() { python3 - "${SHADOW_LOG}" "$1" "$2" <<'PY'
import json, sys
rows = [json.loads(l) for l in open(sys.argv[1]) if l.strip()]
for r in rows:
    if r["proposal_id"] == sys.argv[2]:
        print(r.get(sys.argv[3]))
        break
else:
    print("MISSING")
PY
}
assert_eq "$(get prop_good would_apply)" "True" "shadow auto-apply: qualifying proposal -> would_apply true"
assert_eq "$(get prop_regress would_apply)" "False" "shadow auto-apply: eval-blocked proposal -> would_apply false"
assert_contains "$(get prop_regress reason)" "eval" "shadow auto-apply: eval-blocked reason names the eval"
assert_eq "$(get prop_check would_apply)" "False" "shadow auto-apply: check-surface proposal skipped without a demonstration"
assert_contains "$(get prop_check reason)" "demonstration" "shadow auto-apply: check reason names the demonstration"
assert_eq "$(get prop_lowconf would_apply)" "False" "shadow auto-apply: low confidence -> would_apply false"
assert_contains "$(get prop_lowconf reason)" "confidence" "shadow auto-apply: low-confidence reason"
assert_eq "$(get prop_legacy would_apply)" "True" "shadow auto-apply: legacy proposal without fix_surface reads as rule"
assert_eq "$(get prop_good fingerprint)" "fp-good" "shadow auto-apply: record carries the fingerprint"
assert_eq "$(get prop_check fix_surface)" "check" "shadow auto-apply: record carries the surface"
ts_present="$(python3 -c "import json; print(all('ts' in json.loads(l) for l in open('${SHADOW_LOG}') if l.strip()))")"
assert_eq "${ts_present}" "True" "shadow auto-apply: every record has a ts"

# A same-day re-run appends again; agreement counts each proposal once.
run_auto_apply_rerun() {
    CCGM_AUTOHEAL_CONFIG="${TMPROOT}/auto-config.json" CCGM_AUTOHEAL_PROPOSALS_DIR="${PROPS}" \
    CCGM_AUTOHEAL_APPLIED_DIR="${TMPROOT}/applied" CCGM_AUTOHEAL_SHADOW_DIR="${TMPROOT}/shadow" \
    CCGM_AUTOHEAL_LOGS_DIR="${TMPROOT}/logs" CCGM_AUTOHEAL_TODAY="${TODAY}" \
    CCGM_AUTOHEAL_CLONE_ROOT="${CLONE}" CCGM_AUTOHEAL_EVAL_SCENARIOS="${SCENARIOS}" \
    bash "${AUTO_APPLY_SH}" >/dev/null 2>&1
}
run_auto_apply_rerun
rows="$(grep -c . "${SHADOW_LOG}")"
assert_eq "${rows}" "10" "shadow auto-apply: re-run appends (5 proposals x 2 runs)"

# Boolean back-compat: `true` still applies for real; `false` does nothing.
out="$(run_auto_apply '{"auto_apply_enabled": true}')"
assert_contains "$(cd "${CLONE}" && git branch --list 'autoheal/auto/prop_good')" "autoheal/auto/prop_good" "active (persisted true): applies"
assert_eq "$(cd "${CLONE}" && git branch --list 'autoheal/auto/prop_check')" "" "active: check-surface proposal still not applied"
assert_eq "$(ls "${TMPROOT}/shadow" 2>/dev/null | wc -l | tr -d ' ')" "0" "active: writes no shadow log"
(cd "${CLONE}" && git checkout -q main && git branch -q -D autoheal/auto/prop_good autoheal/auto/prop_legacy 2>/dev/null)

out="$(run_auto_apply '{"auto_apply_enabled": false}')"
assert_eq "$(cd "${CLONE}" && git branch --list 'autoheal/auto/*')" "" "off (persisted false): nothing applied"
assert_eq "$(ls "${TMPROOT}/shadow" 2>/dev/null | wc -l | tr -d ' ')" "0" "off: writes no shadow log"
out="$(run_auto_apply '{"auto_apply_enabled": "off"}')"
assert_eq "$(ls "${TMPROOT}/shadow" 2>/dev/null | wc -l | tr -d ' ')" "0" "off (string): writes no shadow log"

# --- 5. realtime scanner shadow ---------------------------------------
RT_HOME="${TMPROOT}/rt-home"
mkdir -p "${RT_HOME}/.claude/lib" "${RT_HOME}/autoheal"
cp "${REPO_ROOT}/modules/hooks/lib/hook_utils.py" "${RT_HOME}/.claude/lib/hook_utils.py"
run_rt() {
    # Args: config-json. Prints stderr; sets RT_RC.
    printf '%s\n' "$1" > "${RT_HOME}/autoheal/config.json"
    rm -rf "${RT_HOME}/autoheal/shadow" "${RT_HOME}/autoheal/events"
    local payload
    payload="$(python3 -c "import json; print(json.dumps({'hook_event_name':'PostToolUse','session_id':'s-rt','tool_name':'Bash','tool_input':{'command':'rm -rf /'},'cwd':'/tmp/x'}))")"
    RT_ERR="$(printf '%s' "${payload}" | HOME="${RT_HOME}" CCGM_AUTOHEAL_DIR="${RT_HOME}/autoheal" \
        CCGM_REALTIME_PATTERNS="${LIB}/realtime-security-patterns.json" python3 "${HOOK}" 2>&1 >/dev/null)"
    RT_RC=$?
}
run_rt '{"realtime_alerts_enabled": "shadow"}'
assert_eq "${RT_RC}" "0" "shadow realtime: exit 0 on a matching command"
assert_not_contains "${RT_ERR}" "<autoheal-security-alert>" "shadow realtime: no alert block"
RT_LOG="${RT_HOME}/autoheal/shadow/realtime.jsonl"
assert_eq "$(test -f "${RT_LOG}" && echo yes || echo no)" "yes" "shadow realtime: would_alert log written"
rt_row="$(head -1 "${RT_LOG}" 2>/dev/null)"
assert_contains "${rt_row}" '"would_alert": true' "shadow realtime: record says would_alert true"
assert_contains "${rt_row}" '"pattern"' "shadow realtime: record names the pattern"
assert_not_contains "${rt_row}" "rm -rf" "shadow realtime: record does not store the command"
assert_eq "$(test -e "${RT_HOME}/autoheal/events" && echo yes || echo no)" "no" "shadow realtime: no event logged"

run_rt '{"realtime_alerts_enabled": true}'
assert_eq "${RT_RC}" "2" "active realtime (persisted true): exit 2"
assert_contains "${RT_ERR}" "<autoheal-security-alert>" "active realtime: alert block emitted"
assert_eq "$(test -e "${RT_HOME}/autoheal/shadow" && echo yes || echo no)" "no" "active realtime: no shadow log"
run_rt '{"realtime_alerts_enabled": "active"}'
assert_eq "${RT_RC}" "2" "active realtime (string): exit 2"
run_rt '{"realtime_alerts_enabled": false}'
assert_eq "${RT_RC}" "0" "off realtime (persisted false): exit 0"
assert_eq "$(test -e "${RT_HOME}/autoheal/shadow" && echo yes || echo no)" "no" "off realtime: no shadow log"

# Missing autoheal_mode.py (partial install): the hook does nothing, silently.
ORPHAN="${TMPROOT}/orphan-hook"
mkdir -p "${ORPHAN}"
cp "${HOOK}" "${ORPHAN}/realtime-security-scanner.py"
printf '%s\n' '{"realtime_alerts_enabled": "active"}' > "${RT_HOME}/autoheal/config.json"
rm -rf "${RT_HOME}/autoheal/shadow" "${RT_HOME}/autoheal/events"
orphan_payload="$(python3 -c "import json; print(json.dumps({'hook_event_name':'PostToolUse','session_id':'s-rt','tool_name':'Bash','tool_input':{'command':'rm -rf /'},'cwd':'/tmp/x'}))")"
orphan_out="$(printf '%s' "${orphan_payload}" | HOME="${RT_HOME}" CCGM_AUTOHEAL_DIR="${RT_HOME}/autoheal" \
    CCGM_REALTIME_PATTERNS="${LIB}/realtime-security-patterns.json" \
    python3 "${ORPHAN}/realtime-security-scanner.py" 2>&1)"
assert_eq "$?" "0" "missing autoheal_mode: hook exits 0"
assert_eq "${orphan_out}" "" "missing autoheal_mode: no output"
assert_eq "$(test -e "${RT_HOME}/autoheal/events" && echo yes || echo no)" "no" "missing autoheal_mode: no event written"
assert_eq "$(test -e "${RT_HOME}/autoheal/shadow" && echo yes || echo no)" "no" "missing autoheal_mode: no shadow log"

# --- 6. digest ---------------------------------------------------------
DG="${TMPROOT}/dg"
mkdir -p "${DG}/proposals" "${DG}/shadow" "${DG}/applied"
jq -nc '{id:"prop_x",kind:"settings_allow_add",title:"X",rationale:"r",confidence:9,breadth_score:1,occurrence_count:3}' > "${DG}/proposals/2026-06-01.jsonl"
python3 - "${DG}" <<'PY'
import json, sys
d = sys.argv[1]
rows = [
    {"ts": "t", "proposal_id": "a", "would_apply": True, "reason": "ok", "fingerprint": "fp-a", "fix_surface": "rule"},
    {"ts": "t", "proposal_id": "b", "would_apply": True, "reason": "ok", "fingerprint": "fp-b", "fix_surface": "rule"},
    {"ts": "t", "proposal_id": "c", "would_apply": False, "reason": "x", "fingerprint": "fp-c", "fix_surface": "rule"},
    {"ts": "t", "proposal_id": "e", "would_apply": True, "reason": "ok", "fingerprint": "fp-e", "fix_surface": "rule"},
]
open(d + "/shadow/auto-apply.jsonl", "w").write("".join(json.dumps(r) + "\n" for r in rows))
open(d + "/applied/2026-06-01.jsonl", "w").write(
    json.dumps({"proposal_id": "a", "tests_passed": True, "rolled_back": False}) + "\n" +
    json.dumps({"proposal_id": "c", "tests_passed": True, "rolled_back": False}) + "\n" +
    json.dumps({"proposal_id": "e", "tests_passed": False, "rolled_back": True}) + "\n")
json.dump({"fp-b": "2026-07-01T00:00:00Z"}, open(d + "/snoozed.json", "w"))
open(d + "/shadow/realtime.jsonl", "w").write(
    json.dumps({"ts": "t", "session_id": "s", "pattern": "p", "would_alert": True}) + "\n")
PY
run_digest() {
    CCGM_AUTOHEAL_PROPOSALS_DIR="${DG}/proposals" CCGM_AUTOHEAL_DIGESTS_DIR="${DG}/digests" \
    CCGM_AUTOHEAL_SENT_DIR="${DG}/sent" CCGM_AUTOHEAL_CONFIG="${DG}/none.json" \
    CCGM_AUTOHEAL_SHADOW_DIR="${DG}/shadow" CCGM_AUTOHEAL_APPLIED_DIR="${DG}/applied" \
    CCGM_AUTOHEAL_SNOOZED_FILE="${DG}/snoozed.json" \
    CCGM_AUTOHEAL_TODAY="2026-06-01" CCGM_AUTOHEAL_LIB_DIR="${REPO_ROOT}/modules/hooks/lib" \
    bash "${DIGEST_SH}" >/dev/null 2>&1
    cat "${DG}/digests/2026-06-01.md" 2>/dev/null
}
digest="$(run_digest)"
assert_contains "${digest}" "## Shadow rollout" "digest: has a shadow section"
assert_contains "${digest}" "shadow auto-apply decisions: 4" "digest: decision count"
assert_contains "${digest}" "agreed: 1" "digest: agreed (applied a)"
assert_contains "${digest}" "1 false positive, 1 false negative" "digest: b snoozed is a false positive, c applied is a false negative"
assert_contains "${digest}" "pending (no human outcome yet): 1" "digest: e's only apply record failed, so it stays pending"
assert_contains "${digest}" "would-alert matches: 1" "digest: realtime would_alert count"
assert_contains "${digest}" "promotion bar not met" "digest: promotion status"

rm -rf "${DG}/shadow"
digest="$(run_digest)"
assert_not_contains "${digest}" "Shadow rollout" "digest: no shadow section without shadow logs"

# --- 7. toggle ---------------------------------------------------------
TG="${TMPROOT}/toggle.json"
echo '{"email_enabled": false, "auto_apply_enabled": false}' > "${TG}"
out="$(py "${MODE_PY}" set "${TG}" autoapply shadow)"
assert_eq "${out}" "set auto_apply_enabled = shadow" "toggle: autoapply shadow confirmation"
assert_eq "$(jq -r .auto_apply_enabled "${TG}")" "shadow" "toggle: autoapply shadow written"
assert_eq "$(jq -r .email_enabled "${TG}")" "false" "toggle: other keys preserved"
py "${MODE_PY}" set "${TG}" realtime shadow >/dev/null
assert_eq "$(jq -r .realtime_alerts_enabled "${TG}")" "shadow" "toggle: realtime shadow written"
py "${MODE_PY}" set "${TG}" autoapply on >/dev/null
assert_eq "$(jq -r .auto_apply_enabled "${TG}")" "active" "toggle: on -> active"
py "${MODE_PY}" set "${TG}" autoapply off >/dev/null
assert_eq "$(jq -r .auto_apply_enabled "${TG}")" "off" "toggle: off -> off"
py "${MODE_PY}" set "${TG}" autoapply active >/dev/null
assert_eq "$(jq -r .auto_apply_enabled "${TG}")" "active" "toggle: active accepted"
py "${MODE_PY}" set "${TG}" autoapply bogus >/dev/null 2>&1
assert_eq "$?" "2" "toggle: junk value is rejected with exit 2"
assert_eq "$(jq -r .auto_apply_enabled "${TG}")" "active" "toggle: junk value leaves the file unchanged"
assert_eq "$(py "${MODE_PY}" status "${TG}" autoapply)" "auto_apply_enabled = active" "toggle: status prints the mode"
rm -f "${TMPROOT}/new.json"
py "${MODE_PY}" set "${TMPROOT}/new.json" realtime shadow >/dev/null
assert_eq "$(jq -r .realtime_alerts_enabled "${TMPROOT}/new.json")" "shadow" "toggle: creates a missing config"

echo ""
echo "test-shadow-mode.sh: ${PASS} passed, ${FAIL} failed"
[ "${FAIL}" -eq 0 ] || exit 1
exit 0
