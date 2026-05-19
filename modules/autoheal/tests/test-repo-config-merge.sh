#!/usr/bin/env bash
# test-repo-config-merge.sh
#
# Verifies hook_utils.load_repo_config() (Epic 1) when invoked from the
# autoheal side (Epic 12).
#
# Properties exercised:
#   - Walks upward from a nested subdir to the first .autoheal/config.json
#   - Returns the parsed dict verbatim (additional_allow_patterns kept)
#   - Missing config → returns {}
#   - Malformed config → returns {} (analyzer must not crash on user
#     JSON typos in a per-repo override)
#   - The repo-config-schema.json declares additionalProperties:false,
#     so an attempt to inject a top-level field that COULD widen security
#     (e.g. a phantom "allow_remove_deny_patterns") is documented as
#     out-of-schema. The runtime helper preserves unknown keys
#     (forward-compat) — but downstream consumers only read documented
#     fields, which is the actual security boundary.
#
# Run: bash modules/autoheal/tests/test-repo-config-merge.sh

set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MODULE_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
REPO_ROOT="$(cd "${MODULE_ROOT}/../.." && pwd)"
HOOK_LIB="${REPO_ROOT}/modules/hooks/lib"
SCHEMA_PATH="${MODULE_ROOT}/lib/repo-config-schema.json"

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

if [ ! -f "${HOOK_LIB}/hook_utils.py" ]; then
    echo "FATAL: hook_utils.py missing at ${HOOK_LIB}"
    exit 1
fi
if [ ! -f "${SCHEMA_PATH}" ]; then
    echo "FATAL: repo-config-schema.json missing at ${SCHEMA_PATH}"
    exit 1
fi

TMP=$(mktemp -d -t repo_cfg_test.XXXXXX)
trap 'rm -rf "${TMP}"' EXIT

# Build a fake repo tree with a nested cwd far below the .autoheal dir.
REPO="${TMP}/fake-repo"
NESTED="${REPO}/src/server/api"
mkdir -p "${NESTED}"
mkdir -p "${REPO}/.autoheal"

# A typical per-repo override: additional_allow_patterns + a kind filter
# + a thresholds bump. This matches the Supabase fixture intent
# documented in plan.md §3.4.
cat > "${REPO}/.autoheal/config.json" <<'JSON'
{
  "additional_allow_patterns": ["Bash(supabase:*)", "Bash(wrangler:*)"],
  "calibration_days": 7,
  "thresholds": {"confidence_min": 6, "occurrence_min": 3},
  "kind_filters": ["settings_allow_add"]
}
JSON

# ---------------------------------------------------------------------------
# 1. Walk from nested cwd → returns the dict verbatim.
# ---------------------------------------------------------------------------

result_json="$(CCGM_TEST_CWD="${NESTED}" PYTHONPATH="${HOOK_LIB}" python3 - <<'PY'
import json, os
import hook_utils
cfg = hook_utils.load_repo_config(os.environ["CCGM_TEST_CWD"])
print(json.dumps(cfg, sort_keys=True))
PY
)"

# Field-by-field assertions on the result.
n_allow="$(printf '%s' "${result_json}" | python3 -c 'import sys,json; print(len(json.load(sys.stdin).get("additional_allow_patterns", [])))')"
assert_eq "${n_allow}" "2" "additional_allow_patterns list length"

first_pat="$(printf '%s' "${result_json}" | python3 -c 'import sys,json; print(json.load(sys.stdin)["additional_allow_patterns"][0])')"
assert_eq "${first_pat}" "Bash(supabase:*)" "additional_allow_patterns[0] preserved"

second_pat="$(printf '%s' "${result_json}" | python3 -c 'import sys,json; print(json.load(sys.stdin)["additional_allow_patterns"][1])')"
assert_eq "${second_pat}" "Bash(wrangler:*)" "additional_allow_patterns[1] preserved"

cal_days="$(printf '%s' "${result_json}" | python3 -c 'import sys,json; print(json.load(sys.stdin)["calibration_days"])')"
assert_eq "${cal_days}" "7" "calibration_days passed through"

conf_min="$(printf '%s' "${result_json}" | python3 -c 'import sys,json; print(json.load(sys.stdin)["thresholds"]["confidence_min"])')"
assert_eq "${conf_min}" "6" "thresholds.confidence_min passed through"

occ_min="$(printf '%s' "${result_json}" | python3 -c 'import sys,json; print(json.load(sys.stdin)["thresholds"]["occurrence_min"])')"
assert_eq "${occ_min}" "3" "thresholds.occurrence_min passed through"

n_kinds="$(printf '%s' "${result_json}" | python3 -c 'import sys,json; print(len(json.load(sys.stdin)["kind_filters"]))')"
assert_eq "${n_kinds}" "1" "kind_filters list length"

first_kind="$(printf '%s' "${result_json}" | python3 -c 'import sys,json; print(json.load(sys.stdin)["kind_filters"][0])')"
assert_eq "${first_kind}" "settings_allow_add" "kind_filters[0] preserved"

# ---------------------------------------------------------------------------
# 2. Missing config → {} . Use a sibling subtree with no .autoheal.
# ---------------------------------------------------------------------------

OTHER="${TMP}/other-repo/src"
mkdir -p "${OTHER}"
result_empty="$(CCGM_TEST_CWD="${OTHER}" PYTHONPATH="${HOOK_LIB}" python3 - <<'PY'
import json, os
import hook_utils
print(json.dumps(hook_utils.load_repo_config(os.environ["CCGM_TEST_CWD"])))
PY
)"
assert_eq "${result_empty}" "{}" "missing config returns {}"

# ---------------------------------------------------------------------------
# 3. Malformed JSON → {} (must not raise).
# ---------------------------------------------------------------------------

BAD="${TMP}/bad-repo"
mkdir -p "${BAD}/.autoheal" "${BAD}/src"
echo '{ "additional_allow_patterns": [ "Bash(broken' > "${BAD}/.autoheal/config.json"

result_bad="$(CCGM_TEST_CWD="${BAD}/src" PYTHONPATH="${HOOK_LIB}" python3 - <<'PY'
import json, os
import hook_utils
print(json.dumps(hook_utils.load_repo_config(os.environ["CCGM_TEST_CWD"])))
PY
)"
assert_eq "${result_bad}" "{}" "malformed config returns {}"

# ---------------------------------------------------------------------------
# 4. Schema sanity check (Epic 12): the schema is valid JSON and exposes
# the documented top-level fields. We don't fail if jsonschema isn't
# installed; that's a soft check.
# ---------------------------------------------------------------------------

schema_ok="$(SCHEMA_PATH="${SCHEMA_PATH}" python3 - <<'PY'
import json, os, sys
with open(os.environ["SCHEMA_PATH"]) as fh:
    s = json.load(fh)
required_props = {
    "additional_allow_patterns",
    "calibration_days",
    "thresholds",
    "kind_filters",
}
props = set((s.get("properties") or {}).keys())
missing = required_props - props
if missing:
    print(f"missing-props:{sorted(missing)}")
    sys.exit(1)
# additionalProperties must be False so an attacker can't sneak in a
# deny-removal field. plan.md §R21.
if s.get("additionalProperties") is not False:
    print("additionalProperties-not-false")
    sys.exit(1)
print("ok")
PY
)"
assert_eq "${schema_ok}" "ok" "repo-config-schema.json sanity"

echo ""
echo "test-repo-config-merge.sh: ${PASS} passed, ${FAIL} failed"
[ "${FAIL}" -eq 0 ] || exit 1
exit 0
