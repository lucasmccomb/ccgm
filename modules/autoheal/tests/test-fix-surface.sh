#!/usr/bin/env bash
# test-fix-surface.sh (#1077)
#
# Every autoheal proposal names the one surface that fixes it:
# check (hook, test, lint), rule, tool, or access. Verifies:
#   1. proposal-schema.json carries a required fix_surface enum.
#   2. The analyzer accepts a valid fix_surface and rejects an invalid or
#      missing one.
#   3. The digest shows the surface; a legacy proposal without the field
#      renders as `rule`.
#   4. apply-proposal.py reads a legacy proposal as `rule`, refuses a
#      `check` proposal without a failing demonstration, and validates
#      the demonstration it records.
#   5. The analyzer prompt and /autoheal-apply doc name the surface rules.
#
# Run: bash modules/autoheal/tests/test-fix-surface.sh

set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MODULE_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
REPO_ROOT="$(cd "${MODULE_ROOT}/../.." && pwd)"
ANALYZER="${MODULE_ROOT}/bin/autoheal-analyze.sh"
DIGEST="${MODULE_ROOT}/bin/autoheal-digest.sh"
APPLY_LIB="${MODULE_ROOT}/lib/apply-proposal.py"
SCHEMA="${MODULE_ROOT}/lib/proposal-schema.json"

PASS=0
FAIL=0
TMPROOT="$(mktemp -d -t autoheal-fix-surface.XXXXXX)"
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
            echo "  in (first 400): ${1:0:400}"
            ;;
    esac
}

# --- 1. schema ---------------------------------------------------------
SCHEMA_CHECK="$(python3 - "${SCHEMA}" <<'PY'
import json, sys
s = json.load(open(sys.argv[1]))
enum = s["properties"].get("fix_surface", {}).get("enum")
ok = enum == ["check", "rule", "tool", "access"] and "fix_surface" in s["required"]
print("OK" if ok else f"bad: {enum}")
PY
)"
assert_eq "${SCHEMA_CHECK}" "OK" "schema: fix_surface is a required four-value enum"

# --- 2. analyzer -------------------------------------------------------
YESTERDAY=$(python3 -c "import datetime as dt; print((dt.date.today()-dt.timedelta(days=1)).isoformat())")
TODAY=$(python3 -c "import datetime; print(datetime.datetime.now(datetime.timezone.utc).date().isoformat())")

run_analyzer_case() {
    # Args: label surface ("" omits the field).
    local label="$1" surface="$2"
    local home="${TMPROOT}/an_${label}"
    mkdir -p "${home}/autoheal/events"
    python3 - "${home}" "${YESTERDAY}" "${label}" "${surface}" <<'PY'
import datetime as dt, json, sys
home, day, label, surface = sys.argv[1:5]
now = dt.datetime.now(dt.timezone.utc).isoformat()
with open(f"{home}/autoheal/events/{day}.jsonl", "w") as fh:
    fh.write(json.dumps({"kind": "permission_request", "timestamp": now, "session_id": "s-1",
                         "tool_name": "Bash", "redacted_command": "git diff", "cwd": "/tmp/r"}) + "\n")
prop = {
    "id": f"prop_{label}", "kind": "settings_allow_add", "title": "t", "rationale": "r",
    "confidence": 9, "breadth_score": 2, "occurrence_count": 2, "session_ids": ["a", "b"],
    "proposed_diff_target": "modules/settings/settings.partial.json", "proposed_diff": "+ x",
    "fingerprint": "0" * 64, "originating_clone": "ccgm-w1-c0",
    "generated_at": "2026-05-18T08:00:00+00:00",
}
if surface:
    prop["fix_surface"] = surface
resp = {"id": "m", "type": "message", "role": "assistant", "model": "claude-sonnet-4-6",
        "usage": {"input_tokens": 1, "output_tokens": 1},
        "content": [{"type": "text", "text": json.dumps({"proposals": [prop]})}]}
json.dump(resp, open(f"{home}/fixture.json", "w"))
PY
    echo "2020-01-01" > "${home}/autoheal/last-analyzed"
    touch -t 202001010000 "${home}/autoheal/last-analyzed" 2>/dev/null || true
    env HOME="${home}" CCGM_AUTOHEAL_DIR="${home}/autoheal" \
        CCGM_AUTOHEAL_FIXTURE_API_RESPONSE="${home}/fixture.json" \
        CCGM_AUTOHEAL_TODAY="${TODAY}" CCGM_AUTOHEAL_CLONE_ID="ccgm-w1-c0" ANTHROPIC_API_KEY="x" \
        bash "${ANALYZER}" >"${home}/run.out" 2>"${home}/run.err"
}

run_analyzer_case valid check
accepted="$(cat "${TMPROOT}/an_valid/autoheal/proposals/${TODAY}.jsonl" 2>/dev/null)"
assert_contains "${accepted}" '"fix_surface": "check"' "analyzer: valid fix_surface accepted and persisted"

for bad in bogus ""; do
    label="bad${bad:-missing}"
    run_analyzer_case "${label}" "${bad}"
    size="$(wc -c 2>/dev/null < "${TMPROOT}/an_${label}/autoheal/proposals/${TODAY}.jsonl" | tr -d ' ')"
    assert_eq "${size:-0}" "0" "analyzer: fix_surface '${bad:-<missing>}' is not persisted"
    rej="$(cat "${TMPROOT}/an_${label}/.claude/logs/autoheal-rejected-${TODAY}.log" 2>/dev/null)"
    assert_contains "${rej}" "fix_surface" "analyzer: fix_surface '${bad:-<missing>}' rejection is logged"
done

# --- 3. digest ---------------------------------------------------------
PROPS="${TMPROOT}/dg/proposals"
mkdir -p "${PROPS}"
jq -nc '{id:"prop_new",kind:"settings_allow_add",title:"New",rationale:"r",confidence:9,breadth_score:1,occurrence_count:3,fix_surface:"check"}' >> "${PROPS}/2026-06-01.jsonl"
jq -nc '{id:"prop_old",kind:"rule_update",title:"Legacy",rationale:"r",confidence:5,breadth_score:1,occurrence_count:1}' >> "${PROPS}/2026-06-01.jsonl"
CCGM_AUTOHEAL_PROPOSALS_DIR="${PROPS}" CCGM_AUTOHEAL_DIGESTS_DIR="${TMPROOT}/dg/d" \
    CCGM_AUTOHEAL_SENT_DIR="${TMPROOT}/dg/s" CCGM_AUTOHEAL_CONFIG="${TMPROOT}/dg/none.json" \
    CCGM_AUTOHEAL_TODAY="2026-06-01" CCGM_AUTOHEAL_LIB_DIR="${REPO_ROOT}/modules/hooks/lib" \
    bash "${DIGEST}" >/dev/null 2>&1
digest="$(cat "${TMPROOT}/dg/d/2026-06-01.md" 2>/dev/null)"
new_block="$(printf '%s\n' "${digest}" | sed -n '/^### New/,/^Apply:/p')"
old_block="$(printf '%s\n' "${digest}" | sed -n '/^### Legacy/,/^Apply:/p')"
assert_contains "${new_block}" '- **surface**: `check`' "digest: shows the proposal's surface"
assert_contains "${old_block}" '- **surface**: `rule`' "digest: legacy proposal without the field renders as rule"

# --- 4. apply-proposal -------------------------------------------------
APPLY_OUT="$(CCGM_AUTOHEAL_PROPOSALS_DIR="${TMPROOT}/ap/p" CCGM_AUTOHEAL_APPLIED_DIR="${TMPROOT}/ap/a" \
    CCGM_AUTOHEAL_TODAY="2026-06-01" python3 - "${APPLY_LIB}" <<'PY'
import importlib.util, json, os, sys
spec = importlib.util.spec_from_file_location("ap", sys.argv[1])
ap = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ap)
out = []
out.append("legacy=" + ap.fix_surface({"id": "x"}))
out.append("explicit=" + ap.fix_surface({"fix_surface": "tool"}))
good = {"command": "bash tests/t.sh", "clean_exit": 0, "violation": "added a bad line",
        "violation_exit": 1, "reverted": True}
out.append("good=" + str(ap.demonstration_problem(good)))
out.append("noviol=" + str(ap.demonstration_problem({**good, "violation_exit": 0}) is not None))
out.append("dirty=" + str(ap.demonstration_problem({**good, "clean_exit": 1}) is not None))
out.append("unreverted=" + str(ap.demonstration_problem({**good, "reverted": False}) is not None))
out.append("missing=" + str(ap.demonstration_problem(None) is not None))
os.makedirs(os.environ["CCGM_AUTOHEAL_PROPOSALS_DIR"])
with open(os.path.join(os.environ["CCGM_AUTOHEAL_PROPOSALS_DIR"], "2026-06-01.jsonl"), "w") as fh:
    fh.write(json.dumps({"id": "prop_chk", "fix_surface": "check"}) + "\n")
r = ap.apply_proposal("prop_chk")
out.append("refused=" + str(not r["success"] and "demonstration" in (r["error"] or "")))
print("\n".join(out))
PY
)"
assert_contains "${APPLY_OUT}" "legacy=rule" "apply: missing fix_surface reads as rule"
assert_contains "${APPLY_OUT}" "explicit=tool" "apply: explicit fix_surface is kept"
assert_contains "${APPLY_OUT}" "good=None" "apply: complete demonstration passes"
assert_contains "${APPLY_OUT}" "noviol=True" "apply: a check that passes on the violation is rejected"
assert_contains "${APPLY_OUT}" "dirty=True" "apply: a check that fails on clean code is rejected"
assert_contains "${APPLY_OUT}" "unreverted=True" "apply: an unreverted violation is rejected"
assert_contains "${APPLY_OUT}" "missing=True" "apply: no demonstration is rejected"
assert_contains "${APPLY_OUT}" "refused=True" "apply: check proposal without demonstration is refused before any git work"

# --- 5. prompt and command doc ----------------------------------------
assert_contains "$(cat "${MODULE_ROOT}/lib/analyzer-prompt.md")" "fix_surface" "prompt: names fix_surface"
assert_contains "$(cat "${MODULE_ROOT}/lib/analyzer-prompt.md")" 'Prefer `check`' "prompt: prefers check"
assert_contains "$(cat "${MODULE_ROOT}/commands/autoheal-apply.md")" "--demonstration" "apply doc: names the demonstration step"

echo "passed=${PASS} failed=${FAIL}"
[ "${FAIL}" -eq 0 ]
