#!/usr/bin/env bash
# test-shadow-mode.sh (#1087, #1099 Phase 4.2)
#
# realtime_alerts_enabled and auto_apply_mode take off | shadow | active. In
# shadow the decision is computed and logged and nothing else happens. The
# auto-apply step itself (gate, promotion, demotion, active apply) is covered by
# test-auto-apply-gate.sh; this file covers the shared library pieces:
#   1. resolve_mode / read_mode: persisted booleans read as active/off for
#      realtime; auto_apply_mode migrates the legacy flag, never to active.
#   2. agreement(): agree, false positive, false negative, pending, harmful;
#      latest decision per proposal wins; decisions before a demotion are ignored.
#   3. promotion_verdict(): the named-constant bar (10 decided, 90%, 0 harmful).
#   4. realtime-security-scanner.py in shadow: logs would_alert, emits no
#      <autoheal-security-alert> block, exits 0; active mode still alerts.
#   5. autoheal-digest.sh shows the shadow counts and promotion status.
#   6. The toggle writes realtime shadow/on/off and rejects junk.
#
# Run: bash modules/autoheal/tests/test-shadow-mode.sh

set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MODULE_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
REPO_ROOT="$(cd "${MODULE_ROOT}/../.." && pwd)"
LIB="${MODULE_ROOT}/lib"
MODE_PY="${LIB}/autoheal_mode.py"
DIGEST_SH="${MODULE_ROOT}/bin/autoheal-digest.sh"
HOOK="${MODULE_ROOT}/hooks/realtime-security-scanner.py"

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
print(m.read_mode(d + "a.json", "auto_apply_mode"),
      m.read_mode(d + "a.json", "realtime_alerts_enabled"),
      m.read_mode(d + "a.json", "missing_key"),
      m.read_mode(d + "bad.json", "auto_apply_mode"),
      m.read_mode(d + "nope.json", "realtime_alerts_enabled"))
PY
)"
assert_eq "${out}" "shadow shadow off off off" "read_mode: legacy auto-apply true -> shadow, realtime passthrough, missing/bad/absent -> off"
assert_eq "$(py "${MODE_PY}" mode "${TMPROOT}/cfg/a.json" realtime_alerts_enabled)" "shadow" "CLI mode prints the resolved mode"

# --- 2. agreement ------------------------------------------------------
out="$(py - <<'PY'
import datetime as dt
import autoheal_mode as m
G = "2026-09-01T00:00:00+00:00"
def d(pid, would, ts="2026-09-02T00:00:00+00:00"):
    return {"proposal_id": pid, "generated_at": G, "would_apply": would, "ts": ts}
def row(pid, state, **kw):
    return {"id": pid, "generated_at": G, "state": state, **kw}
rows = [row("agree-yes", "applied"), row("agree-no", "rejected"), row("fp", "rejected"),
        row("fn", "measured", outcome="effective"), row("pend", "ready"),
        row("harm", "reverted"), row("auto", "applied", applied_by="auto")]
decisions = [d("agree-yes", True), d("agree-no", False), d("fp", True), d("fn", False), d("pend", True),
             d("harm", True), d("auto", True)]
s = m.agreement(decisions, m.human_outcomes(rows))
print(s["decisions"], s["decided"], s["agreed"], s["false_positives"], s["false_negatives"], s["pending"], s["harmful"])
s = m.agreement([d("p", False), d("p", True)], m.human_outcomes([row("p", "applied")]))
print(s["decisions"], s["agreed"])
since = dt.datetime(2026, 9, 3, tzinfo=dt.timezone.utc)
s = m.agreement([d("old", True), d("new", True, ts="2026-09-04T00:00:00+00:00")],
                m.human_outcomes([row("old", "applied"), row("new", "applied")]), since)
print(s["decisions"], s["agreed"])
# A redrafted signature reuses its id: the generated_at keeps the two proposals apart.
s = m.agreement([{"proposal_id": "x", "generated_at": "g2", "would_apply": True, "ts": "t"}],
                m.human_outcomes([{"id": "x", "generated_at": "g1", "state": "applied"},
                                  {"id": "x", "generated_at": "g2", "state": "ready"}]))
print(s["pending"])
PY
)"
assert_eq "$(printf '%s\n' "${out}" | sed -n 1p)" "7 5 3 1 1 2 1" "agreement: cells, auto-applied rows stay pending, reverted would-apply counts harmful"
assert_eq "$(printf '%s\n' "${out}" | sed -n 2p)" "1 1" "agreement: latest record per proposal wins"
assert_eq "$(printf '%s\n' "${out}" | sed -n 3p)" "1 1" "agreement: decisions before the last demotion are ignored"
assert_eq "$(printf '%s\n' "${out}" | sed -n 4p)" "1" "agreement: decisions match rows by id and generated_at"

# --- 3. promotion bar --------------------------------------------------
out="$(py - <<'PY'
import autoheal_mode as m
def s(agreed, fp=0, fn=0, harmful=0, pending=0):
    return {"decisions": agreed + fp + fn + pending, "decided": agreed + fp + fn, "agreed": agreed,
            "false_positives": fp, "false_negatives": fn, "pending": pending, "harmful": harmful}
v = m.promotion_verdict
print(m.PROMOTION_MIN_DECIDED, m.PROMOTION_MIN_AGREEMENT, m.PROMOTION_MAX_HARMFUL,
      m.DEMOTION_REVERTS, m.DEMOTION_WINDOW_DAYS)
print(v(s(9, fn=1))["ready"], v(s(9))["ready"], v(s(8, fn=2))["ready"],
      v(s(10, harmful=1))["ready"], v(s(5, pending=50))["ready"])
PY
)"
assert_eq "$(printf '%s\n' "${out}" | sed -n 1p)" "10 0.9 0 3 30" "promotion: documented constants"
assert_eq "$(printf '%s\n' "${out}" | sed -n 2p)" "True False False False False" "promotion: met at the bar; short, low agreement, harmful, pending-only all fail"

# --- 4. realtime scanner shadow ---------------------------------------
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

# --- 5. digest ---------------------------------------------------------
DG="${TMPROOT}/dg"
mkdir -p "${DG}/shadow"
python3 - "${DG}" <<'PY'
import json, sys
d = sys.argv[1]
G = "2026-05-30T00:00:00+00:00"
rows = [
    {"id": "a", "generated_at": G, "state": "applied", "kind": "rule_insert", "title": "A"},
    {"id": "b", "generated_at": G, "state": "rejected", "kind": "rule_insert", "title": "B"},
    {"id": "c", "generated_at": G, "state": "measured", "outcome": "effective", "kind": "rule_insert", "title": "C"},
    {"id": "e", "generated_at": G, "state": "ready", "kind": "rule_insert", "title": "E"},
    # A row from the digest day, so the digest renders at all; it has no decision.
    {"id": "x", "generated_at": "2026-06-01T08:00:00Z", "state": "ready", "kind": "rule_insert", "title": "X"},
]
open(d + "/proposals.jsonl", "w").write("".join(json.dumps(r) + "\n" for r in rows))
decs = [
    {"ts": "2026-05-31T00:00:00+00:00", "proposal_id": "a", "generated_at": G, "would_apply": True},
    {"ts": "2026-05-31T00:00:00+00:00", "proposal_id": "b", "generated_at": G, "would_apply": True},
    {"ts": "2026-05-31T00:00:00+00:00", "proposal_id": "c", "generated_at": G, "would_apply": False},
    {"ts": "2026-05-31T00:00:00+00:00", "proposal_id": "e", "generated_at": G, "would_apply": True},
]
open(d + "/shadow/auto-apply.jsonl", "w").write("".join(json.dumps(r) + "\n" for r in decs))
open(d + "/shadow/realtime.jsonl", "w").write(
    json.dumps({"ts": "t", "session_id": "s", "pattern": "p", "would_alert": True}) + "\n")
json.dump({"auto_apply_mode": "shadow"}, open(d + "/config.json", "w"))
PY
run_digest() {
    CCGM_AUTOHEAL_DIR="${DG}" CCGM_AUTOHEAL_LEDGER="${DG}/proposals.jsonl" CCGM_AUTOHEAL_DIGESTS_DIR="${DG}/digests" \
    CCGM_AUTOHEAL_SENT_DIR="${DG}/sent" CCGM_AUTOHEAL_CONFIG="${DG}/config.json" \
    CCGM_AUTOHEAL_SHADOW_DIR="${DG}/shadow" \
    CCGM_AUTOHEAL_TODAY="2026-06-01" CCGM_AUTOHEAL_LIB_DIR="${REPO_ROOT}/modules/hooks/lib" \
    bash "${DIGEST_SH}" >/dev/null 2>&1
    cat "${DG}/digests/2026-06-01.md" 2>/dev/null
}
digest="$(run_digest)"
assert_contains "${digest}" "## Shadow rollout" "digest: has a shadow section"
assert_contains "${digest}" "auto-apply mode: shadow" "digest: mode"
assert_contains "${digest}" "shadow auto-apply decisions: 4" "digest: decision count"
assert_contains "${digest}" "agreed: 1 of 3 decided" "digest: a applied agrees"
assert_contains "${digest}" "1 false positive, 1 false negative" "digest: b rejected is a false positive, c applied is a false negative"
assert_contains "${digest}" "pending (no review decision yet): 1" "digest: e is still ready"
assert_contains "${digest}" "would-alert matches: 1" "digest: realtime would_alert count"
assert_contains "${digest}" "promotion bar not met" "digest: promotion status"

rm -rf "${DG}/shadow"
digest="$(run_digest)"
assert_not_contains "${digest}" "Shadow rollout" "digest: no shadow section without shadow logs"

# --- 6. toggle (realtime; autoapply is covered by test-auto-apply-gate.sh) ---
TG="${TMPROOT}/toggle.json"
echo '{"email_enabled": false}' > "${TG}"
out="$(py "${MODE_PY}" set "${TG}" realtime shadow)"
assert_eq "${out}" "set realtime_alerts_enabled = shadow" "toggle: realtime shadow confirmation"
assert_eq "$(jq -r .realtime_alerts_enabled "${TG}")" "shadow" "toggle: realtime shadow written"
assert_eq "$(jq -r .email_enabled "${TG}")" "false" "toggle: other keys preserved"
py "${MODE_PY}" set "${TG}" realtime on >/dev/null
assert_eq "$(jq -r .realtime_alerts_enabled "${TG}")" "active" "toggle: on -> active"
py "${MODE_PY}" set "${TG}" realtime off >/dev/null
assert_eq "$(jq -r .realtime_alerts_enabled "${TG}")" "off" "toggle: off -> off"
py "${MODE_PY}" set "${TG}" realtime bogus >/dev/null 2>&1
assert_eq "$?" "2" "toggle: junk value is rejected with exit 2"
assert_eq "$(jq -r .realtime_alerts_enabled "${TG}")" "off" "toggle: junk value leaves the file unchanged"
assert_eq "$(py "${MODE_PY}" status "${TG}" realtime)" "realtime_alerts_enabled = off" "toggle: status prints the mode"
rm -f "${TMPROOT}/new.json"
py "${MODE_PY}" set "${TMPROOT}/new.json" realtime shadow >/dev/null
assert_eq "$(jq -r .realtime_alerts_enabled "${TMPROOT}/new.json")" "shadow" "toggle: creates a missing config"

echo ""
echo "test-shadow-mode.sh: ${PASS} passed, ${FAIL} failed"
[ "${FAIL}" -eq 0 ] || exit 1
exit 0
