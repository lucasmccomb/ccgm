#!/usr/bin/env bash
# test-audit-manifest-complete.sh
# Manifest completeness gate: every runtime file inside skills/audit/ must
# have a corresponding entry in modules/commands-extra/module.json's
# "files" map (key = module-relative path).
#
# This is the inverse of the mapped->exists check in tests/test-modules.sh.
# That test verifies: for each key in files[], the file exists on disk.
# This test verifies: for each file on disk, there is a key in files[].
#
# RUNTIME files = all files under skills/audit/ EXCLUDING:
#   - tests/           (test suite, not installed)
#   - fixtures/        (test fixtures, not installed)
#   - __pycache__/     (Python bytecode, not installed)
#   - *.pyc            (Python bytecode, not installed)
#
# Non-vacuity proof:
#   The test creates a throwaway unregistered .py file, confirms the test
#   FAILS (catching the unregistered file), then removes it and confirms
#   the test PASSES on the real tree.
#
# Usage: bash modules/commands-extra/skills/audit/tests/test-audit-manifest-complete.sh
# Exit:  0 = all runtime files registered; non-zero = unregistered files found

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
AUDIT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
MODULE_DIR="$(cd "${AUDIT_DIR}/../.." && pwd)"   # modules/commands-extra/
MODULE_JSON="${MODULE_DIR}/module.json"

PASS_COUNT=0
FAIL_COUNT=0
FAILURES=()

pass() {
  local name="$1"
  printf '  PASS: %s\n' "$name"
  PASS_COUNT=$((PASS_COUNT + 1))
}

fail() {
  local name="$1"
  local detail="${2:-}"
  printf '  FAIL: %s%s\n' "$name" "${detail:+ -- $detail}"
  FAIL_COUNT=$((FAIL_COUNT + 1))
  FAILURES+=("${name}${detail:+: $detail}")
}

# ---------------------------------------------------------------------------
# check_manifest: walk skills/audit/, return unregistered file paths.
# Arguments: optional extra_file (a path to treat as if it exists on disk
#            even if the OS hasn't seen it yet -- used for non-vacuity proof)
# Exit code: 0 if all files registered; 1 if any unregistered.
# Prints one line per unregistered file to stdout.
# ---------------------------------------------------------------------------
check_manifest() {
  local extra_file="${1:-}"
  python3 - "$MODULE_JSON" "$AUDIT_DIR" "$MODULE_DIR" "$extra_file" << 'PYEOF'
import json, os, sys

module_json_path = sys.argv[1]
audit_dir        = sys.argv[2]
module_dir       = sys.argv[3]
extra_file       = sys.argv[4] if len(sys.argv) > 4 else ""

with open(module_json_path) as f:
    mod = json.load(f)

registered = set(mod.get("files", {}).keys())

# Collect runtime files on disk
EXCLUDED_DIRS = {"__pycache__", "tests", "fixtures"}
runtime_files = []

for root, dirs, files in os.walk(audit_dir):
    # Prune excluded directories in-place
    dirs[:] = [d for d in dirs if d not in EXCLUDED_DIRS]
    for fname in files:
        if fname.endswith(".pyc"):
            continue
        abs_path = os.path.join(root, fname)
        # Module-relative path (relative to module_dir = modules/commands-extra/)
        rel = os.path.relpath(abs_path, module_dir)
        runtime_files.append(rel)

# Optionally inject a synthetic file for non-vacuity proof
if extra_file:
    rel_extra = os.path.relpath(extra_file, module_dir)
    if rel_extra not in runtime_files:
        runtime_files.append(rel_extra)

unregistered = sorted(f for f in runtime_files if f not in registered)

for u in unregistered:
    print(u)

sys.exit(1 if unregistered else 0)
PYEOF
}

echo ""
echo "=== /audit manifest completeness gate ==="
echo "  audit dir:    ${AUDIT_DIR}"
echo "  module.json:  ${MODULE_JSON}"
echo ""

# ---------------------------------------------------------------------------
# STEP 1: Non-vacuity proof
#   Create a throwaway unregistered .py file in a runtime location.
#   Confirm the gate detects it (exits non-zero).
#   Remove the file. The real check (Step 2) should then pass.
# ---------------------------------------------------------------------------
echo "--- [non-vacuity proof] ---"

FAKE_FILE="${AUDIT_DIR}/scripts/_unregistered_test_fixture.py"

# Clean up any stale fixture from a previous run
rm -f "$FAKE_FILE"

# Create the unregistered file
printf '# unregistered test fixture -- should be caught by manifest gate\n' > "$FAKE_FILE"

PROBE_OUTPUT=""
PROBE_EXIT=0
set +e
PROBE_OUTPUT="$(check_manifest "" 2>&1)"
PROBE_EXIT=$?
set -e

# Remove the fixture immediately regardless of result
rm -f "$FAKE_FILE"

if [[ $PROBE_EXIT -ne 0 ]]; then
  # Gate correctly detected the unregistered file
  # Herestring, not a pipe: `producer | grep -q` can SIGPIPE-kill the
  # producer if grep exits on its first match before the producer finishes
  # writing, turning a genuine match into a reported failure (see #943,
  # #945). A herestring has no second process to race against.
  if grep -q "_unregistered_test_fixture.py" <<< "$PROBE_OUTPUT"; then
    pass "non-vacuity: gate FAILS when an unregistered file is present (correctly detected ${FAKE_FILE##*/})"
  else
    pass "non-vacuity: gate FAILS when an unregistered file is present (exit ${PROBE_EXIT})"
  fi
else
  # Gate silently passed -- the test is vacuous
  fail "non-vacuity: gate passed with an unregistered file present -- check_manifest is not walking the right directory" \
    "probe output: ${PROBE_OUTPUT:-<empty>}"
fi

echo ""

# ---------------------------------------------------------------------------
# STEP 2: Real tree check
#   Run the gate against the actual skills/audit/ tree.
#   Every runtime file must have a registered entry.
# ---------------------------------------------------------------------------
echo "--- [manifest completeness: skills/audit/ runtime files] ---"

UNREGISTERED_FILES=""
MANIFEST_EXIT=0
set +e
UNREGISTERED_FILES="$(check_manifest "" 2>&1)"
MANIFEST_EXIT=$?
set -e

if [[ $MANIFEST_EXIT -eq 0 ]]; then
  pass "all runtime files in skills/audit/ are registered in module.json"
else
  # Report each unregistered file as a separate failure
  echo "  Unregistered files found (each must be added to modules/commands-extra/module.json):"
  while IFS= read -r line; do
    [[ -z "$line" ]] && continue
    fail "unregistered runtime file" "$line"
    echo "    ${line}"
  done <<< "$UNREGISTERED_FILES"
fi

echo ""

# ---------------------------------------------------------------------------
# STEP 3: Verify module.json is valid JSON (sanity guard)
# ---------------------------------------------------------------------------
echo "--- [module.json sanity] ---"

set +e
python3 -c "import json; json.load(open('${MODULE_JSON}'))" 2>/dev/null
JSON_EXIT=$?
set -e

if [[ $JSON_EXIT -eq 0 ]]; then
  pass "module.json is valid JSON"
else
  fail "module.json is NOT valid JSON -- parse error"
fi

echo ""

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
echo "=== Results: ${PASS_COUNT} passed, ${FAIL_COUNT} failed ==="

if [[ "${#FAILURES[@]}" -gt 0 ]]; then
  echo ""
  echo "Failures:"
  for f in "${FAILURES[@]}"; do
    echo "  - ${f}"
  done
  echo ""
  echo "To fix: add each unregistered file to modules/commands-extra/module.json"
  echo "under the 'files' key with the appropriate target, type, and template fields."
  echo ""
  exit 1
fi

echo ""
exit 0
