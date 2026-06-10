#!/usr/bin/env bash
# test-pack-validate.sh
# Suite-level gate: validate every pack under packs/ (excluding _TEMPLATE) against
# pack.schema.json AND assert every checks[].id has an entry in severity-rubric.json.
#
# Deliverable 1 for GitHub issue #645 (Epic 5.2).
#
# Two gates, both run for every pack:
#   GATE 1 -- pack.json schema validation via registry.py's validate_pack
#   GATE 2 -- orphan check-id gate: every check id in pack.json must appear
#             in severity-rubric.json's "checks" map
#
# Exit: 0 = all packs pass both gates; 1 = at least one failure.
#
# Usage: bash modules/commands-extra/skills/audit/tests/test-pack-validate.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
AUDIT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
SCRIPTS_DIR="${AUDIT_DIR}/scripts"
PACKS_DIR="${AUDIT_DIR}/packs"
RUBRIC_FILE="${AUDIT_DIR}/schemas/severity-rubric.json"
REGISTRY="${SCRIPTS_DIR}/registry.py"

PASS=0
FAIL=0
ERRORS=()

pass() {
  printf '  [PASS] %s\n' "$1"
  PASS=$((PASS + 1))
}

fail() {
  printf '  [FAIL] %s\n' "$1"
  ERRORS+=("$1")
  FAIL=$((FAIL + 1))
}

echo ""
echo "=== test-pack-validate.sh (Epic 5.2, Deliverable 1) ==="
echo ""

# ---------------------------------------------------------------------------
# Pre-flight checks
# ---------------------------------------------------------------------------
for f in "$REGISTRY" "$RUBRIC_FILE" "$PACKS_DIR"; do
  if [ ! -e "$f" ]; then
    echo "ERROR: required path not found: $f" >&2
    exit 1
  fi
done

if ! command -v python3 >/dev/null 2>&1; then
  echo "ERROR: python3 is required" >&2
  exit 1
fi

# ---------------------------------------------------------------------------
# Load rubric checks map once (suite-wide)
# ---------------------------------------------------------------------------
RUBRIC_CHECKS_JSON="$(python3 - "$RUBRIC_FILE" << 'PYEOF'
import json, sys
with open(sys.argv[1]) as fh:
    rubric = json.load(fh)
checks = rubric.get("checks", {})
print(json.dumps(list(checks.keys())))
PYEOF
)"

echo "--- [1] Pack schema validation + orphan check-id gate ---"
echo ""

# Discover pack directories (excluding _TEMPLATE)
PACK_DIRS=()
while IFS= read -r -d '' d; do
  pack_json="$d/pack.json"
  [ -f "$pack_json" ] && PACK_DIRS+=("$d")
done < <(find "$PACKS_DIR" -maxdepth 1 -mindepth 1 -type d \
  -not -name '_TEMPLATE' -print0 2>/dev/null | sort -z)

if [ "${#PACK_DIRS[@]}" -eq 0 ]; then
  echo "ERROR: no pack directories found under $PACKS_DIR" >&2
  exit 1
fi

echo "  Found ${#PACK_DIRS[@]} pack(s) (excluding _TEMPLATE)"
echo ""

TOTAL_PACKS=0
TOTAL_CHECKS_VALIDATED=0
ORPHAN_IDS=()

for pack_dir in "${PACK_DIRS[@]}"; do
  pack_name="$(basename "$pack_dir")"
  pack_json="$pack_dir/pack.json"
  TOTAL_PACKS=$((TOTAL_PACKS + 1))

  # GATE 1: schema validation via registry.py's validate_pack
  SCHEMA_RESULT="$(python3 - "$pack_json" "$REGISTRY" << 'PYEOF'
import importlib.util, json, sys

pack_json_path, registry_path = sys.argv[1], sys.argv[2]

# Load registry module
spec = importlib.util.spec_from_file_location("registry", registry_path)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

try:
    with open(pack_json_path) as fh:
        pack = json.load(fh)
except json.JSONDecodeError as exc:
    print("JSON_ERROR:" + str(exc))
    sys.exit(0)

try:
    mod.validate_pack(pack, pack_json_path)
    # Return check ids for orphan gate
    check_ids = [c["id"] for c in pack.get("checks", []) if isinstance(c, dict)]
    print("OK:" + ",".join(check_ids))
except mod.ValidationError as exc:
    print("INVALID:" + str(exc))
PYEOF
)"

  if [[ "$SCHEMA_RESULT" == OK:* ]]; then
    pass "schema: $pack_name/pack.json"
    CHECK_IDS_CSV="${SCHEMA_RESULT#OK:}"

    # GATE 2: orphan check-id gate
    if [ -z "$CHECK_IDS_CSV" ]; then
      # pack has empty checks — schema validation would already have caught this,
      # but be defensive
      fail "orphan-gate: $pack_name has no check ids (unexpected after schema pass)"
      continue
    fi

    # Evaluate each check id against the rubric
    ORPHAN_RESULT="$(python3 - "$CHECK_IDS_CSV" "$RUBRIC_CHECKS_JSON" "$pack_name" << 'PYEOF'
import json, sys
check_ids_csv, rubric_json, pack_name = sys.argv[1], sys.argv[2], sys.argv[3]
rubric_ids = set(json.loads(rubric_json))
check_ids = [c for c in check_ids_csv.split(",") if c]
orphans = [c for c in check_ids if c not in rubric_ids]
if orphans:
    print("ORPHANS:" + ",".join(orphans))
else:
    print("OK:" + str(len(check_ids)))
PYEOF
)"

    if [[ "$ORPHAN_RESULT" == OK:* ]]; then
      NCHECK="${ORPHAN_RESULT#OK:}"
      pass "orphan-gate: $pack_name ($NCHECK check id(s) all in rubric)"
      TOTAL_CHECKS_VALIDATED=$((TOTAL_CHECKS_VALIDATED + NCHECK))
    elif [[ "$ORPHAN_RESULT" == ORPHANS:* ]]; then
      ORPHAN_LIST="${ORPHAN_RESULT#ORPHANS:}"
      fail "orphan-gate: $pack_name -- check id(s) missing from rubric: $ORPHAN_LIST"
      ORPHAN_IDS+=("$pack_name: $ORPHAN_LIST")
    else
      fail "orphan-gate: $pack_name -- unexpected result: $ORPHAN_RESULT"
    fi

  elif [[ "$SCHEMA_RESULT" == INVALID:* ]]; then
    REASON="${SCHEMA_RESULT#INVALID:}"
    fail "schema: $pack_name/pack.json -- $REASON"
  elif [[ "$SCHEMA_RESULT" == JSON_ERROR:* ]]; then
    REASON="${SCHEMA_RESULT#JSON_ERROR:}"
    fail "schema: $pack_name/pack.json -- invalid JSON: $REASON"
  else
    fail "schema: $pack_name/pack.json -- unexpected validator output: $SCHEMA_RESULT"
  fi
done

echo ""
echo "--- [2] Suite summary ---"
echo ""
echo "  Packs validated : $TOTAL_PACKS"
echo "  Check ids cross-checked against rubric: $TOTAL_CHECKS_VALIDATED"
if [ "${#ORPHAN_IDS[@]}" -gt 0 ]; then
  echo "  Orphan check ids:"
  for o in "${ORPHAN_IDS[@]}"; do
    echo "    - $o"
  done
fi

echo ""
echo "=== Results: $PASS passed, $FAIL failed ==="

if [ "${#ERRORS[@]}" -gt 0 ]; then
  echo ""
  echo "Failures:"
  for e in "${ERRORS[@]}"; do
    echo "  - $e"
  done
  echo ""
  exit 1
fi

echo ""
exit 0
