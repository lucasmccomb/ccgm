#!/usr/bin/env bash
# test-orchestration.sh
# Tests for Epic 1.7b: registry-driven orchestration (assign-packs.py + pipeline integration).
#
# Four test groups:
#   1. Selection:   detector + registry against 3 fixture repos
#   2. Assignment:  assign-packs.py determinism, balance, coverage
#   3. Pipeline:    spine -> merge with gitleaks fake-key e2e (ADV-001 gate)
#   4. Consistency: SKILL.md structure checks (legacy markers gone, new markers present)
#
# All fixtures are constructed at runtime in mktemp dirs; none are tracked.
# ADV-009: fake AWS key is assembled from fragments at runtime (never appears assembled
#          in this source file).
#
# Usage: bash modules/commands-extra/skills/audit/tests/test-orchestration.sh
# Exit:  0 = all pass, non-zero = at least one failure

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
AUDIT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
SCRIPTS_DIR="${AUDIT_DIR}/scripts"
PACKS_DIR="${AUDIT_DIR}/packs"
SKILL_MD="${AUDIT_DIR}/SKILL.md"
SCHEMAS_DIR="${AUDIT_DIR}/schemas"

DETECT="${SCRIPTS_DIR}/detect-ecosystems.sh"
REGISTRY="${SCRIPTS_DIR}/registry.py"
ASSIGN="${SCRIPTS_DIR}/assign-packs.py"
SPINE="${SCRIPTS_DIR}/spine/run.sh"
MERGE="${SCRIPTS_DIR}/merge-findings.py"
RUBRIC="${SCHEMAS_DIR}/severity-rubric.json"

PASS=0
FAIL=0
ERRORS=()

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
pass() {
  printf '  [PASS] %s\n' "$1"
  PASS=$((PASS + 1))
}

fail() {
  printf '  [FAIL] %s\n' "$1"
  ERRORS+=("$1")
  FAIL=$((FAIL + 1))
}

# Sorted comma-separated pack id list from a JSON array file
pack_ids_sorted() {
  python3 - "$1" << 'PYEOF'
import json, sys
packs = json.load(open(sys.argv[1]))
ids = sorted(p["id"] for p in packs)
print(",".join(ids))
PYEOF
}

# Cleanup temp dirs on exit
TMPDIRS=()
cleanup() {
  for d in "${TMPDIRS[@]:-}"; do
    rm -rf "$d" 2>/dev/null || true
  done
}
trap cleanup EXIT

make_tmp() {
  local d
  d=$(mktemp -d)
  TMPDIRS+=("$d")
  echo "$d"
}

# ---------------------------------------------------------------------------
# Prerequisite checks
# ---------------------------------------------------------------------------
echo ""
echo "=== test-orchestration.sh (Epic 1.7b) ==="
echo ""

for tool in python3 jq git; do
  if ! command -v "$tool" >/dev/null 2>&1; then
    echo "ERROR: required tool '$tool' not found" >&2
    exit 1
  fi
done

for f in "$DETECT" "$REGISTRY" "$ASSIGN" "$SPINE" "$MERGE" "$RUBRIC" "$SKILL_MD"; do
  if [ ! -f "$f" ]; then
    echo "ERROR: required file not found: $f" >&2
    exit 1
  fi
done

# ---------------------------------------------------------------------------
# GROUP 1: Selection -- detector + registry against 3 fixture repos
# ---------------------------------------------------------------------------
echo "--- [1] Pack selection: detector + registry against fixture repos ---"
echo ""

# Expected pack id sets (derived from pack.json applies_when values, Wave 4 state):
#   Always-packs (applies_when=["always"]): 12 packs:
#     ccgm/architecture, ccgm/ccgm-hygiene, ccgm/ccgm-standards, ccgm/code-quality,
#     ccgm/documentation, ccgm/observability, ccgm/performance, ccgm/privacy,
#     ccgm/secrets, ccgm/security, ccgm/testing, ccgm/tos-compliance
#   JS-gated (applies_when=["language:javascript"]): 6 packs:
#     ccgm/accessibility, ccgm/api-contract, ccgm/correctness, ccgm/dependencies,
#     ccgm/reliability, ccgm/typescript-react
#   has_migrations-gated: ccgm/data-migrations
#   has_iac-gated:        ccgm/infra-iac
#   has_workflows-gated:  ccgm/ci-cd
#
# Fixture A: JS+TS -> 18 packs (12 always + 6 JS-gated, no migrations/iac/workflows)
EXPECTED_A="ccgm/accessibility,ccgm/api-contract,ccgm/architecture,ccgm/ccgm-hygiene,ccgm/ccgm-standards,ccgm/code-quality,ccgm/correctness,ccgm/dependencies,ccgm/documentation,ccgm/observability,ccgm/performance,ccgm/privacy,ccgm/reliability,ccgm/secrets,ccgm/security,ccgm/testing,ccgm/tos-compliance,ccgm/typescript-react"

# Fixture B: Go only -> 12 always-packs (no JS/TS files, no migrations, no iac, no workflows)
EXPECTED_B="ccgm/architecture,ccgm/ccgm-hygiene,ccgm/ccgm-standards,ccgm/code-quality,ccgm/documentation,ccgm/observability,ccgm/performance,ccgm/privacy,ccgm/secrets,ccgm/security,ccgm/testing,ccgm/tos-compliance"

# Fixture C: migrations + JS -> 19 packs (12 always + 6 JS-gated + data-migrations)
EXPECTED_C="ccgm/accessibility,ccgm/api-contract,ccgm/architecture,ccgm/ccgm-hygiene,ccgm/ccgm-standards,ccgm/code-quality,ccgm/correctness,ccgm/data-migrations,ccgm/dependencies,ccgm/documentation,ccgm/observability,ccgm/performance,ccgm/privacy,ccgm/reliability,ccgm/secrets,ccgm/security,ccgm/testing,ccgm/tos-compliance,ccgm/typescript-react"

# Fixture A: JS+TS
FIX_A=$(make_tmp)
echo '{}' > "$FIX_A/package.json"
echo '{"compilerOptions":{}}' > "$FIX_A/tsconfig.json"
printf 'export const x = 1;\n' > "$FIX_A/index.ts"

# Fixture B: Go
FIX_B=$(make_tmp)
printf 'module example.com/myapp\n\ngo 1.21\n' > "$FIX_B/go.mod"
printf 'package main\nfunc main() {}\n' > "$FIX_B/main.go"

# Fixture C: migrations + JS
FIX_C=$(make_tmp)
echo '{}' > "$FIX_C/package.json"
mkdir -p "$FIX_C/supabase/migrations"
echo '-- create users' > "$FIX_C/supabase/migrations/0001_users.sql"

echo "  Fixture A: JS+TS (package.json + tsconfig.json + .ts file)"
set +e
DET_A=$(bash "$DETECT" "$FIX_A" 2>/dev/null)
REG_A_FILE=$(make_tmp)/selected.json
echo "$DET_A" | CCGM_PACKS_DIR="$PACKS_DIR" python3 "$REGISTRY" > "$REG_A_FILE" 2>/dev/null
ACTUAL_A=$(pack_ids_sorted "$REG_A_FILE" 2>/dev/null || echo "ERROR")
set -e

if [ "$ACTUAL_A" = "$EXPECTED_A" ]; then
  pass "fixture A (JS+TS): selected 18 packs (12 always + 6 JS-gated)"
else
  fail "fixture A (JS+TS): expected '$EXPECTED_A' but got '$ACTUAL_A'"
fi

echo "  Fixture B: Go only (go.mod + main.go, no JS/TS)"
set +e
DET_B=$(bash "$DETECT" "$FIX_B" 2>/dev/null)
REG_B_FILE=$(make_tmp)/selected.json
echo "$DET_B" | CCGM_PACKS_DIR="$PACKS_DIR" python3 "$REGISTRY" > "$REG_B_FILE" 2>/dev/null
ACTUAL_B=$(pack_ids_sorted "$REG_B_FILE" 2>/dev/null || echo "ERROR")
set -e

if [ "$ACTUAL_B" = "$EXPECTED_B" ]; then
  pass "fixture B (Go): selected 12 always-packs (no JS-gated packs)"
else
  fail "fixture B (Go): expected '$EXPECTED_B' but got '$ACTUAL_B'"
fi

echo "  Fixture C: migrations + JS (supabase/migrations/ + package.json)"
set +e
DET_C=$(bash "$DETECT" "$FIX_C" 2>/dev/null)
REG_C_FILE=$(make_tmp)/selected.json
echo "$DET_C" | CCGM_PACKS_DIR="$PACKS_DIR" python3 "$REGISTRY" > "$REG_C_FILE" 2>/dev/null
ACTUAL_C=$(pack_ids_sorted "$REG_C_FILE" 2>/dev/null || echo "ERROR")
set -e

if [ "$ACTUAL_C" = "$EXPECTED_C" ]; then
  pass "fixture C (migrations+JS): selected 19 packs (12 always + 6 JS-gated + data-migrations)"
else
  fail "fixture C (migrations+JS): expected '$EXPECTED_C' but got '$ACTUAL_C'"
fi

# Verify fixture C has has_migrations=true in detection output
set +e
HAS_MIG=$(echo "$DET_C" | python3 -c 'import json,sys; d=json.load(sys.stdin); print(str(d["project_shape"]["has_migrations"]).lower())' 2>/dev/null || echo "error")
set -e
if [ "$HAS_MIG" = "true" ]; then
  pass "fixture C: detection correctly reports has_migrations=true"
else
  fail "fixture C: detection should report has_migrations=true (got '$HAS_MIG')"
fi

# Verify fixture B shows no javascript/typescript in detected_ecosystems
set +e
B_ECOSSYS=$(echo "$DET_B" | python3 -c 'import json,sys; d=json.load(sys.stdin); ecoss=d["detected_ecosystems"]; print("ok" if "javascript" not in ecoss and "typescript" not in ecoss else "fail")' 2>/dev/null || echo "error")
set -e
if [ "$B_ECOSSYS" = "ok" ]; then
  pass "fixture B: no javascript/typescript in detected_ecosystems"
else
  fail "fixture B: javascript or typescript should NOT be in detected_ecosystems"
fi

# ---------------------------------------------------------------------------
# GROUP 2: Assignment -- assign-packs.py determinism, balance, coverage
# ---------------------------------------------------------------------------
echo ""
echo "--- [2] Pack assignment: assign-packs.py determinism, balance, coverage ---"
echo ""

# Use a fixed selected-packs JSON (9 packs — fixture A result)
FIXED_PACKS_FILE=$(make_tmp)/fixed-packs.json
python3 - "$FIXED_PACKS_FILE" "$PACKS_DIR" << 'PYEOF'
import json, os, sys
out_file, packs_dir = sys.argv[1], sys.argv[2]
packs = []
for d in sorted(os.listdir(packs_dir)):
    pf = os.path.join(packs_dir, d, "pack.json")
    if os.path.isfile(pf):
        packs.append(json.load(open(pf)))
json.dump(packs, open(out_file, "w"), indent=2)
PYEOF

ASSIGN_OUT_1=$(make_tmp)/assign1.json
ASSIGN_OUT_2=$(make_tmp)/assign2.json

set +e
python3 "$ASSIGN" "$FIXED_PACKS_FILE" --workers 4 > "$ASSIGN_OUT_1" 2>/dev/null
EC1=$?
python3 "$ASSIGN" "$FIXED_PACKS_FILE" --workers 4 > "$ASSIGN_OUT_2" 2>/dev/null
EC2=$?
set -e

if [ "$EC1" -eq 0 ] && [ "$EC2" -eq 0 ]; then
  pass "assign-packs.py: both runs succeeded (exit 0)"
else
  fail "assign-packs.py: one or both runs failed (exit codes: $EC1, $EC2)"
fi

# Determinism: byte-identical output
if diff -q "$ASSIGN_OUT_1" "$ASSIGN_OUT_2" >/dev/null 2>&1; then
  pass "assign-packs.py: same input produces byte-identical output (deterministic)"
else
  fail "assign-packs.py: output differs between two runs with same input (non-deterministic)"
fi

# All packs assigned exactly once
set +e
COVERAGE_CHECK=$(python3 - "$ASSIGN_OUT_1" "$FIXED_PACKS_FILE" << 'PYEOF'
import json, sys
assignment = json.load(open(sys.argv[1]))
packs = json.load(open(sys.argv[2]))
all_pack_ids = set(p["id"] for p in packs)
assigned_ids = []
for worker_packs in assignment.values():
    assigned_ids.extend(worker_packs)
assigned_set = set(assigned_ids)
if len(assigned_ids) != len(assigned_set):
    print("DUPLICATE")
elif assigned_set != all_pack_ids:
    missing = all_pack_ids - assigned_set
    extra = assigned_set - all_pack_ids
    print(f"MISMATCH: missing={missing} extra={extra}")
else:
    print("OK")
PYEOF
)
set -e

if [ "$COVERAGE_CHECK" = "OK" ]; then
  pass "assign-packs.py: all packs assigned exactly once"
else
  fail "assign-packs.py: assignment coverage error: $COVERAGE_CHECK"
fi

# Balance check: assert no worker receives more than ceil(total_packs/workers)+1 packs
# (pack-count bound). The greedy algorithm minimizes check-load imbalance, but the pack-count
# bound is the weaker structural assertion we can make deterministically from the fixture.
# No-starvation property: when packs >= workers, every worker must receive >= 1 pack.
# The greedy assignment guarantees this because it assigns packs one-by-one in sorted order;
# with 9 packs and 4 workers the first 4 iterations each touch a different worker.
set +e
BALANCE_CHECK=$(python3 - "$ASSIGN_OUT_1" "$FIXED_PACKS_FILE" << 'PYEOF'
import json, sys, math
assignment = json.load(open(sys.argv[1]))
packs_by_id = {p["id"]: p for p in json.load(open(sys.argv[2]))}

# Compute check-count load per worker
worker_check_loads = {}
for wid, pack_ids in assignment.items():
    total = sum(len(packs_by_id.get(pid, {}).get("checks", [])) for pid in pack_ids)
    worker_check_loads[wid] = total

loads = list(worker_check_loads.values())
max_load = max(loads)
min_load = min(loads)
pack_count_per_worker = [len(v) for v in assignment.values()]
max_packs = max(pack_count_per_worker)

# No worker should have more than ceil(total_packs / workers) + 1 packs
total_packs = sum(pack_count_per_worker)
num_workers = len(loads)
ceil_share = math.ceil(total_packs / num_workers)
overloaded = [k for k, v in assignment.items() if len(v) > ceil_share + 1]

# No-starvation assertion: when packs >= workers, every worker gets >= 1 pack
starved = []
if total_packs >= num_workers:
    starved = [k for k, v in assignment.items() if len(v) == 0]

if overloaded:
    print(f"OVERLOADED: workers {overloaded} have too many packs (ceil_share={ceil_share})")
elif starved:
    print(f"STARVED: workers {starved} have 0 packs despite packs({total_packs}) >= workers({num_workers})")
else:
    print(f"OK: max_check_load={max_load} min_check_load={min_load} max_packs_per_worker={max_packs}")
PYEOF
)
set -e

if echo "$BALANCE_CHECK" | grep -q "^OK"; then
  pass "assign-packs.py: worker pack distribution is balanced (no overload, no starvation) ($BALANCE_CHECK)"
else
  fail "assign-packs.py: pack distribution imbalanced ($BALANCE_CHECK)"
fi

# Works correctly when N packs < workers (e.g., 2 packs, 4 workers)
SMALL_PACKS=$(make_tmp)/small-packs.json
python3 - "$SMALL_PACKS" "$PACKS_DIR" << 'PYEOF'
import json, os, sys
out_file, packs_dir = sys.argv[1], sys.argv[2]
packs = []
# Collect only dirs that have a pack.json (skips _TEMPLATE and other non-pack dirs)
pack_dirs = [d for d in sorted(os.listdir(packs_dir))
             if os.path.isfile(os.path.join(packs_dir, d, "pack.json"))]
for d in pack_dirs[:2]:  # only first 2 real packs alphabetically
    pf = os.path.join(packs_dir, d, "pack.json")
    packs.append(json.load(open(pf)))
json.dump(packs, open(out_file, "w"), indent=2)
PYEOF

SMALL_ASSIGN=$(make_tmp)/small-assign.json
set +e
python3 "$ASSIGN" "$SMALL_PACKS" --workers 4 > "$SMALL_ASSIGN" 2>/dev/null
SMALL_EC=$?
set -e

if [ "$SMALL_EC" -eq 0 ]; then
  pass "assign-packs.py: handles N packs < workers (exit 0)"
else
  fail "assign-packs.py: failed when N packs < workers (exit $SMALL_EC)"
fi

set +e
SMALL_CHECK=$(python3 - "$SMALL_ASSIGN" << 'PYEOF'
import json, sys
a = json.load(open(sys.argv[1]))
empty = [k for k, v in a.items() if not v]
non_empty = [k for k, v in a.items() if v]
total_assigned = sum(len(v) for v in a.values())
if len(empty) >= 2 and total_assigned == 2:
    print(f"OK: {len(non_empty)} non-empty workers, {len(empty)} empty workers")
else:
    print(f"UNEXPECTED: empty={empty} non_empty={non_empty} total={total_assigned}")
PYEOF
)
set -e

if echo "$SMALL_CHECK" | grep -q "^OK"; then
  pass "assign-packs.py: surplus workers get empty lists ($SMALL_CHECK)"
else
  fail "assign-packs.py: surplus workers check failed: $SMALL_CHECK"
fi

# ---------------------------------------------------------------------------
# GROUP 3: Pipeline -- spine -> merge with fake AWS key e2e (ADV-001 gate)
# ---------------------------------------------------------------------------
echo ""
echo "--- [3] Pipeline: spine -> merge-findings.py with gitleaks e2e ---"
echo ""

# Build a throwaway git repo with a fake key in the working tree (not committed).
# ADV-009: the assembled key string is CONSTRUCTED AT RUNTIME from fragments.
# The prefix "AKIA" and the suffix chars are never assembled as a literal in this file.
PIPELINE_REPO=$(make_tmp)
git -C "$PIPELINE_REPO" init -q
git -C "$PIPELINE_REPO" config user.email "test@example.com"
git -C "$PIPELINE_REPO" config user.name "Test"

# Commit clean fixture files first (so the repo has a valid HEAD and git history).
# The secret is added AFTER the commit so the pre-commit hook never sees it.
echo '{"name":"test","version":"1.0.0"}' > "$PIPELINE_REPO/package.json"
printf 'export const x = 1;\n' > "$PIPELINE_REPO/index.ts"
git -C "$PIPELINE_REPO" add -A
git -C "$PIPELINE_REPO" commit -q -m "init"

# Now write the fake key into a file in the working tree AFTER the commit.
# The spine uses --no-git (filesystem scan), so it detects this without needing git history.
# ADV-009: high-entropy alphanum key assembled from two fragments at runtime.
# We do NOT use the gitleaks-allowlisted AWS docs example key -- that key is explicitly
# excluded from detection. We use a different high-entropy AWS-format key instead.
KEY_PREFIX="AKIAZ12345"
KEY_SUFFIX="6789ABCDEFGH"
FAKE_KEY="${KEY_PREFIX}${KEY_SUFFIX}"
# Write the key into a config file that gitleaks should detect (working-tree-only)
printf '// This file intentionally contains a test secret for scanner validation\nconst AWS_KEY = "%s";\n' "$FAKE_KEY" > "$PIPELINE_REPO/config.js"

PIPELINE_SPINE_DIR=$(make_tmp)
PIPELINE_SPINE_FILE="$PIPELINE_SPINE_DIR/findings.jsonl"
PIPELINE_MERGE_OUT="$PIPELINE_SPINE_DIR/findings-merged.jsonl"

# Check if gitleaks is available
if command -v gitleaks >/dev/null 2>&1; then
  echo "  gitleaks is available — running spine with gitleaks tool"

  set +e
  bash "$SPINE" \
    --repo  "$PIPELINE_REPO" \
    --tools "gitleaks" \
    --output "$PIPELINE_SPINE_FILE" 2>/dev/null
  SPINE_EC=$?
  set -e

  if [ "$SPINE_EC" -eq 0 ] && [ -f "$PIPELINE_SPINE_FILE" ]; then
    pass "spine: run.sh with gitleaks exited 0"
  else
    fail "spine: run.sh failed (exit $SPINE_EC) or output missing"
  fi

  # Check for at least one finding with source:tool and check_id matching secrets/
  set +e
  SECRETS_FINDING=$(python3 - "$PIPELINE_SPINE_FILE" << 'PYEOF'
import json, sys
count = 0
for line in open(sys.argv[1]):
    line = line.strip()
    if not line:
        continue
    try:
        rec = json.loads(line)
    except Exception:
        continue
    # Skip meta records
    if "type" in rec:
        continue
    cid = rec.get("check_id", "")
    src = rec.get("source", "")
    if src == "tool" and cid.startswith("secrets/"):
        count += 1
print(count)
PYEOF
  )
  set -e

  if [ "${SECRETS_FINDING:-0}" -ge 1 ]; then
    pass "spine: found >= 1 finding with source=tool and check_id starting with 'secrets/'"
  else
    fail "spine: expected >= 1 secrets/ finding from gitleaks, got ${SECRETS_FINDING:-0}"
  fi

  # Run merge-findings.py with just the spine (no LLM results) -- validates coverage_gap passthrough
  set +e
  python3 "$MERGE" \
    --spine  "$PIPELINE_SPINE_FILE" \
    --rubric "$RUBRIC" \
    --repo   "$PIPELINE_REPO" \
    --output "$PIPELINE_MERGE_OUT" 2>/dev/null
  MERGE_EC=$?
  set -e

  if [ "$MERGE_EC" -eq 0 ] && [ -f "$PIPELINE_MERGE_OUT" ]; then
    pass "merge-findings.py: ran successfully with spine-only input"
  else
    fail "merge-findings.py: failed (exit $MERGE_EC) or output missing"
  fi

  # Assert merged output contains at least one finding (the spine secret)
  set +e
  MERGED_COUNT=$(python3 - "$PIPELINE_MERGE_OUT" << 'PYEOF'
import json, sys
count = 0
for line in open(sys.argv[1]):
    line = line.strip()
    if not line:
        continue
    try:
        rec = json.loads(line)
    except Exception:
        continue
    if "type" not in rec:
        count += 1
print(count)
PYEOF
  )
  set -e

  if [ "${MERGED_COUNT:-0}" -ge 1 ]; then
    pass "merge-findings.py: output contains >= 1 finding (spine secret passed through)"
  else
    fail "merge-findings.py: expected >= 1 finding in merged output, got ${MERGED_COUNT:-0}"
  fi

  # Verify the fake key does NOT appear in merged output (redaction check)
  if grep -q "$FAKE_KEY" "$PIPELINE_MERGE_OUT" 2>/dev/null; then
    fail "merge-findings.py: assembled fake key appears unredacted in output -- redaction failed"
  else
    pass "merge-findings.py: assembled fake key NOT in merged output (redaction held)"
  fi

  # Assert the merged output contains a finding with check_id==secrets/leaked-credential,
  # severity==critical, and source==tool (rubric applied through merge -- ADV-001 gate).
  set +e
  CRITICAL_LEAKED=$(python3 - "$PIPELINE_MERGE_OUT" << 'PYEOF'
import json, sys
for line in open(sys.argv[1]):
    line = line.strip()
    if not line:
        continue
    try:
        rec = json.loads(line)
    except Exception:
        continue
    if "type" in rec:
        continue
    cid = rec.get("check_id", "")
    sev = rec.get("severity", "")
    src = rec.get("source", "")
    if cid == "secrets/leaked-credential" and sev == "critical" and src == "tool":
        print("FOUND")
        sys.exit(0)
print("NOT_FOUND")
PYEOF
  )
  set -e

  if [ "${CRITICAL_LEAKED:-}" = "FOUND" ]; then
    pass "merge-findings.py: merged output has check_id=secrets/leaked-credential, severity=critical, source=tool"
  else
    fail "merge-findings.py: expected finding with check_id=secrets/leaked-credential + severity=critical + source=tool" \
      "rubric must be applied at merge time; verify severity-rubric.json has secrets/leaked-credential:critical"
  fi

else
  echo "  gitleaks not installed -- skipping spine e2e (SKIP, not FAIL)"
  echo "  SKIP: spine e2e: gitleaks not available"
  echo "  SKIP: spine e2e: merge with spine output"
  echo "  SKIP: spine e2e: redaction check"
  echo "  SKIP: spine e2e: critical-finding rubric assert"
fi

# Test coverage_gap passthrough with an uninstalled tool.
# Dynamically find the first spine tool NOT on PATH; skip the sub-test if all are installed.
COVERAGE_SPINE=$(make_tmp)/coverage-spine.jsonl
COVERAGE_MERGE=$(make_tmp)/coverage-merged.jsonl

# Discover spine tool list from selected-packs or fall back to a known list.
# The spine supports: gitleaks, actionlint, eslint, shellcheck, semgrep.
SPINE_TOOLS_KNOWN="gitleaks actionlint semgrep shellcheck"
ABSENT_TOOL=""
for t in $SPINE_TOOLS_KNOWN; do
  if ! command -v "$t" >/dev/null 2>&1; then
    ABSENT_TOOL="$t"
    break
  fi
done

if [ -z "$ABSENT_TOOL" ]; then
  echo "  All known spine tools are installed -- skipping coverage_gap sub-test (SKIP, not FAIL)"
  echo "  SKIP: coverage_gap sub-test: no absent tool found"
  echo "  SKIP: coverage_gap sub-test: merge with coverage-only spine"
  echo "  SKIP: coverage_gap sub-test: coverage_gap in merged output"
else
  echo "  Using absent tool '$ABSENT_TOOL' for coverage_gap sub-test"

  set +e
  bash "$SPINE" \
    --repo  "$PIPELINE_REPO" \
    --tools "$ABSENT_TOOL" \
    --output "$COVERAGE_SPINE" 2>/dev/null
  COVERAGE_SPINE_EC=$?
  set -e

  if [ "$COVERAGE_SPINE_EC" -eq 0 ]; then
    pass "spine: runs successfully even when tool '$ABSENT_TOOL' is absent"
  else
    fail "spine: should exit 0 even when tool '$ABSENT_TOOL' is absent (got exit $COVERAGE_SPINE_EC)"
  fi

  # Check that a coverage_gap record exists in the spine output
  set +e
  GAP_COUNT=$(python3 - "$COVERAGE_SPINE" << 'PYEOF'
import json, sys
count = 0
for line in open(sys.argv[1]):
    line = line.strip()
    if not line:
        continue
    try:
        rec = json.loads(line)
    except Exception:
        continue
    if rec.get("type") == "coverage_gap":
        count += 1
print(count)
PYEOF
  )
  set -e

  if [ "${GAP_COUNT:-0}" -ge 1 ]; then
    pass "spine: emits coverage_gap record when tool '$ABSENT_TOOL' is absent (got $GAP_COUNT)"
  else
    fail "spine: expected >= 1 coverage_gap record for absent tool '$ABSENT_TOOL', got ${GAP_COUNT:-0}"
  fi

  # Merge with the coverage-only spine -- coverage_gaps should fold through to merged output
  set +e
  python3 "$MERGE" \
    --spine  "$COVERAGE_SPINE" \
    --rubric "$RUBRIC" \
    --repo   "$PIPELINE_REPO" \
    --output "$COVERAGE_MERGE" 2>/dev/null
  COVERAGE_MERGE_EC=$?
  set -e

  if [ "$COVERAGE_MERGE_EC" -eq 0 ]; then
    pass "merge-findings.py: handles spine with only coverage_gap records (exit 0)"
  else
    fail "merge-findings.py: failed on coverage-only spine (exit $COVERAGE_MERGE_EC)"
  fi

  # Assert the coverage_gap record in the MERGED output names the absent tool
  set +e
  MERGED_GAP=$(python3 - "$COVERAGE_MERGE" "$ABSENT_TOOL" << 'PYEOF'
import json, sys
merged_file, absent_tool = sys.argv[1], sys.argv[2]
for line in open(merged_file):
    line = line.strip()
    if not line:
        continue
    try:
        rec = json.loads(line)
    except Exception:
        continue
    if rec.get("type") == "coverage_gap":
        # Require the absent tool's NAME to appear in the tool field
        tool = rec.get("tool", "")
        if absent_tool in tool:
            print("FOUND")
            sys.exit(0)
print("NOT_FOUND")
PYEOF
  )
  set -e

  if [ "${MERGED_GAP:-}" = "FOUND" ]; then
    pass "merge-findings.py: coverage_gap record in merged output names absent tool '$ABSENT_TOOL'"
  else
    fail "merge-findings.py: expected coverage_gap in merged output with tool='$ABSENT_TOOL' (fold-through + tool-name check)"
  fi
fi

# ---------------------------------------------------------------------------
# GROUP 4: Consistency -- SKILL.md structure checks
# ---------------------------------------------------------------------------
echo ""
echo "--- [4] SKILL.md consistency: legacy markers gone, new markers present ---"
echo ""

# 4a. NO "## Category Prompts" heading in any form (the stubs section is fully deleted).
#     Also assert no "### Agent N:" headers remain (old 9-agent architecture is gone).
set +e
CATEGORY_PROMPTS_SECTION=$(grep -c '^## Category Prompts' "$SKILL_MD" 2>/dev/null || true)
set -e
if [ "${CATEGORY_PROMPTS_SECTION:-0}" -eq 0 ]; then
  pass "SKILL.md: no '## Category Prompts' heading of any form (stubs section deleted)"
else
  fail "SKILL.md: '## Category Prompts' heading is still present -- delete the stubs section"
fi

set +e
AGENT_HEADERS=$(grep -cE '^### Agent [0-9]+:' "$SKILL_MD" 2>/dev/null || true)
set -e
if [ "${AGENT_HEADERS:-0}" -eq 0 ]; then
  pass "SKILL.md: no '### Agent N:' headers (old 9-agent architecture fully removed)"
else
  fail "SKILL.md: '### Agent N:' headers are still present -- remove all category-model agent headers"
fi

# 4b. No hardcoded Agent→category table like "Agent 0 | Security, Dependencies"
set +e
AGENT_TABLE=$(grep -c 'Agent 0.*Security.*Dependencies\|Agent 1.*Code Quality.*TypeScript\|Agent 2.*Architecture.*Performance\|Agent 3.*Testing.*Documentation' "$SKILL_MD" 2>/dev/null || true)
set -e
if [ "${AGENT_TABLE:-0}" -eq 0 ]; then
  pass "SKILL.md: no hardcoded Agent N->category assignment table"
else
  fail "SKILL.md: hardcoded Agent N->category assignment table is still present"
fi

# 4c. New pipeline scripts referenced
for script in "detect-ecosystems.sh" "registry.py" "assign-packs.py" "spine/run.sh" "merge-findings.py"; do
  set +e
  REF_COUNT=$(grep -c "$script" "$SKILL_MD" 2>/dev/null || true)
  set -e
  if [ "${REF_COUNT:-0}" -ge 1 ]; then
    pass "SKILL.md: references '$script'"
  else
    fail "SKILL.md: does not reference '$script'"
  fi
done

# 4d. --single section references the spine and merge scripts (proving pipeline integration)
# Note: use state-tracking awk to avoid the same-line open/close trap where the heading line
# matches both the start and end patterns of the range.
set +e
SINGLE_SECTION=$(awk 'found && /^## /{exit} /^## Single-Session Mode/{found=1} found' "$SKILL_MD" 2>/dev/null || true)
set -e
if echo "$SINGLE_SECTION" | grep -q "spine/run.sh\|spine.*run.sh"; then
  pass "SKILL.md: --single section references spine/run.sh"
else
  fail "SKILL.md: --single section must reference spine/run.sh"
fi

if echo "$SINGLE_SECTION" | grep -q "merge-findings.py"; then
  pass "SKILL.md: --single section references merge-findings.py"
else
  fail "SKILL.md: --single section must reference merge-findings.py"
fi

# 4e. --single read-only statement is unambiguous
set +e
READONLY_STMT=$(grep -c 'single.*always read.only\|single.*read.only\|--single.*read-only' "$SKILL_MD" 2>/dev/null || true)
set -e
if [ "${READONLY_STMT:-0}" -ge 1 ]; then
  pass "SKILL.md: --single read-only statement is present"
else
  fail "SKILL.md: --single must have an unambiguous read-only statement"
fi

# 4f. --single + --fix conflict is documented
set +e
FIX_IGNORED=$(grep -c 'single.*--fix.*ignored\|--fix.*ignored.*single\|--single.*--fix' "$SKILL_MD" 2>/dev/null || true)
set -e
if [ "${FIX_IGNORED:-0}" -ge 1 ]; then
  pass "SKILL.md: --single + --fix conflict documented (--fix silently ignored)"
else
  fail "SKILL.md: must document that --fix is ignored when combined with --single"
fi

# 4g. Zero-packs HALT guard is documented
set +e
ZERO_PACKS_HALT=$(grep -c 'zero packs\|HALT.*zero\|zero.*HALT\|registry selected zero' "$SKILL_MD" 2>/dev/null || true)
set -e
if [ "${ZERO_PACKS_HALT:-0}" -ge 1 ]; then
  pass "SKILL.md: zero-packs HALT guard is documented"
else
  fail "SKILL.md: must document HALT when zero packs selected (same guard class as zero-clone halt)"
fi

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
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
