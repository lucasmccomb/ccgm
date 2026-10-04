#!/usr/bin/env bash
# test-fix-surface.sh (#1077)
#
# Every autoheal proposal names the one surface that fixes it:
# check (hook, test, lint), rule, tool, or access. Verifies:
#   1. The schema the drafting model answers has no fix_surface: the model
#      cannot choose its own surface.
#   2. The analyzer sets fix_surface in code: `rule` for a rule_insert,
#      `check` for a hook-denial issue (the fix is a hook change).
#   3. The digest shows the surface; a legacy proposal without the field
#      renders as `rule`.
#   4. apply-proposal.py reads a legacy proposal as `rule`, refuses a
#      `check` proposal without a failing demonstration, and validates
#      the demonstration it records.
#   5. The /autoheal-apply doc names the demonstration rule for `check`.
#
# Run: bash modules/autoheal/tests/test-fix-surface.sh

set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MODULE_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
REPO_ROOT="$(cd "${MODULE_ROOT}/../.." && pwd)"
ANALYZER="${MODULE_ROOT}/bin/autoheal-analyze.sh"
# shellcheck source=analyzer-fixture.sh
. "${SCRIPT_DIR}/analyzer-fixture.sh"
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
print("OK" if "fix_surface" not in json.dumps(s) else "model schema offers fix_surface")
PY
)"
assert_eq "${SCHEMA_CHECK}" "OK" "schema: the model is not asked for fix_surface"

# --- 2. analyzer -------------------------------------------------------
TODAY="2026-10-04"
FS_ROOT="${TMPROOT}/an"
FS_HOME="${FS_ROOT}/home"
FS_AH="${FS_HOME}/.claude/autoheal"
mkdir -p "${FS_AH}"
fx_repo "${FS_ROOT}/repo"
fx_home "${FS_HOME}" "${FS_ROOT}/repo"
fx_curl "${FS_ROOT}/bin" "${FS_ROOT}/fake"
fx_events "${FS_AH}" "${TODAY}" Bash echo zsh_not_found "(eval):1: ==== not found" 8 3
fx_events "${FS_AH}" "${TODAY}" Edit "" hook_denial_branch_guard "BRANCH GUARD: x" 6 2
fx_answer "${FS_ROOT}/fake/messages.response.json" \
    '{"proposal":{"kind":"rule_insert","target_path":"modules/code-quality/rules/code-quality.md","anchor_heading":"Code Standards","insert_markdown":"- Quote separators under zsh."}}'
env HOME="${FS_HOME}" PATH="${FS_ROOT}/bin:${PATH}" FAKE_CURL_DIR="${FS_ROOT}/fake" \
    CCGM_AUTOHEAL_DIR="${FS_AH}" CCGM_AUTOHEAL_TODAY="${TODAY}" ANTHROPIC_API_KEY="x" \
    bash "${ANALYZER}" >"${FS_ROOT}/run.out" 2>"${FS_ROOT}/run.err"
FS_ROWS="${FS_AH}/proposals/${TODAY}.jsonl"
assert_eq "$(python3 -c "
import json
print(sorted((r['kind'], r['fix_surface']) for r in map(json.loads, open('${FS_ROWS}'))))")" \
    "[('issue', 'check'), ('rule_insert', 'rule')]" "analyzer: rule_insert is surface rule, hook-denial issue is surface check"

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

# --- 5. command doc ----------------------------------------------------
assert_contains "$(cat "${MODULE_ROOT}/commands/autoheal-apply.md")" "--demonstration" "apply doc: names the demonstration step"

echo "passed=${PASS} failed=${FAIL}"
[ "${FAIL}" -eq 0 ]
