#!/usr/bin/env bash
# test-smoke-audits.sh
# Three end-to-end smoke audits for Epic 5.2 (GitHub issue #645).
#
# Each smoke builds a runtime git fixture, runs the DOCUMENTED deterministic
# pipeline (detect-ecosystems -> registry -> spine -> merge-findings), and
# asserts the expected critical secrets/leaked-credential finding surfaces.
#
# Fixtures:
#   (a) JS app: package.json + tsconfig.json + index.ts + config.ts with secret
#   (b) Go service: go.mod + main.go + config.go with secret
#   (c) Migrations repo: package.json + supabase/migrations/0001_init.sql + secret
#
# ADV-009: fake AWS key assembled from fragments at runtime -- never whole in file.
# The gitleaks-allowlisted AWS docs example key (suffix IOSFODNN7EXAMPLE) is NOT used.
# grep -nE 'AKIA[A-Z0-9]{12,}' on this file must return empty.
#
# Bash-4 guard: spine/run.sh uses `declare -A` (bash 4+).
# On macOS bash 3.2, spine invocations and gitleaks-dependent assertions are
# SKIPPED (not FAILED) so macOS CI stays green. Ubuntu CI (bash 5) runs them.
#
# Usage: bash modules/commands-extra/skills/audit/tests/test-smoke-audits.sh
# Exit:  0 = all assertions pass; 1 = at least one failure.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
AUDIT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
SCRIPTS_DIR="${AUDIT_DIR}/scripts"
PACKS_DIR="${AUDIT_DIR}/packs"
SCHEMAS_DIR="${AUDIT_DIR}/schemas"

DETECT="${SCRIPTS_DIR}/detect-ecosystems.sh"
REGISTRY="${SCRIPTS_DIR}/registry.py"
SPINE="${SCRIPTS_DIR}/spine/run.sh"
MERGE="${SCRIPTS_DIR}/merge-findings.py"
RUBRIC="${SCHEMAS_DIR}/severity-rubric.json"

PASS=0
FAIL=0
SKIP=0
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

skip() {
  printf '  [SKIP] %s\n' "$1"
  SKIP=$((SKIP + 1))
}

# ---------------------------------------------------------------------------
# Temp dir management
# ---------------------------------------------------------------------------
TMPDIRS=()
cleanup() {
  for d in "${TMPDIRS[@]:-}"; do
    rm -rf "$d" 2>/dev/null || true
  done
}
trap cleanup EXIT

make_tmp() {
  local d
  d=$(mktemp -d /tmp/ccgm-smoke-XXXXXX)
  TMPDIRS+=("$d")
  printf '%s' "$d"
}

# ---------------------------------------------------------------------------
# Prerequisite checks
# ---------------------------------------------------------------------------
echo ""
echo "=== test-smoke-audits.sh (Epic 5.2, Deliverable 2) ==="
echo ""

for tool in python3 jq git; do
  if ! command -v "$tool" >/dev/null 2>&1; then
    echo "ERROR: required tool '$tool' not found" >&2
    exit 1
  fi
done

for f in "$DETECT" "$REGISTRY" "$SPINE" "$MERGE" "$RUBRIC"; do
  if [ ! -f "$f" ]; then
    echo "ERROR: required file not found: $f" >&2
    exit 1
  fi
done

# Check gitleaks availability (used to gate gitleaks-dependent assertions)
GITLEAKS_AVAILABLE=false
if command -v gitleaks >/dev/null 2>&1; then
  GITLEAKS_AVAILABLE=true
fi

# Check bash version (spine requires bash 4+ for declare -A)
BASH_GE4=true
if [ "${BASH_VERSINFO[0]}" -lt 4 ]; then
  BASH_GE4=false
fi

# ---------------------------------------------------------------------------
# ADV-009: assemble the fake AWS key from fragments at runtime.
# Two separate variables; neither is a detectable key on its own.
# We use "BCDFGHJKLMNPQRST" (consonant pattern) -- NOT the gitleaks-allowlisted
# AWS docs example ("IOSFODNN7EXAMPLE").
# ---------------------------------------------------------------------------
KEY_FRAG_A="AKIA"
KEY_FRAG_B="BCDFGHJKLMNPQRST"
FAKE_KEY="${KEY_FRAG_A}${KEY_FRAG_B}"

# ---------------------------------------------------------------------------
# Helper: build a fixture git repo with a git init and an initial commit.
# Args: $1=repo_dir, $2=path to secret file (relative to repo), $3=secret val
# The repo is initialized with core.hooksPath=/dev/null so pre-commit hooks
# never run in the test environment.
# ---------------------------------------------------------------------------
init_repo_with_secret() {
  local repo="$1"
  local secret_relpath="$2"
  local secret_val="$3"

  mkdir -p "$repo"
  git -C "$repo" init -q
  git -C "$repo" config user.email "test@ccgm.test"
  git -C "$repo" config user.name "CCGMTest"
  git -C "$repo" config core.hooksPath /dev/null 2>/dev/null || true

  # Write the secret file (parent dirs already exist in the repo dir)
  local secret_abs="$repo/$secret_relpath"
  mkdir -p "$(dirname "$secret_abs")"
  python3 - "$secret_abs" "$secret_val" << 'PYEOF'
import sys
path, key = sys.argv[1], sys.argv[2]
with open(path, "w") as fh:
    fh.write("// Test fixture: intentionally planted credential for scanner validation\n")
    fh.write('const AWS_ACCESS_KEY_ID = "' + key + '";\n')
PYEOF

  git -C "$repo" add -A
  git -C "$repo" commit -q -m "init"
}

# ---------------------------------------------------------------------------
# Helper: run the full deterministic pipeline for a fixture repo.
# Returns paths to spine output and merged findings via env vars.
# Spine step gated on BASH_GE4 (bash 4+ required for declare -A in run.sh).
# ---------------------------------------------------------------------------
run_pipeline() {
  local fixture_name="$1"   # human label for messages
  local repo_abs="$2"       # absolute path to the fixture repo
  local tools="$3"          # comma-separated spine tool list for this smoke
  local out_dir="$4"        # temp dir for outputs

  local detection_json="$out_dir/detection.json"
  local selected_json="$out_dir/selected.json"
  local spine_jsonl="$out_dir/spine.jsonl"
  local findings_jsonl="$out_dir/findings.jsonl"

  printf '\n  --- pipeline for %s ---\n' "$fixture_name"

  # Step 1: detect-ecosystems
  set +e
  bash "$DETECT" "$repo_abs" > "$detection_json" 2>/dev/null
  DET_EC=$?
  set -e
  if [ "$DET_EC" -eq 0 ] && [ -s "$detection_json" ]; then
    pass "$fixture_name: detect-ecosystems exited 0 and produced output"
  else
    fail "$fixture_name: detect-ecosystems failed (exit $DET_EC) or produced empty output"
    return 1
  fi

  # Step 2: registry.py selection
  set +e
  CCGM_PACKS_DIR="$PACKS_DIR" python3 "$REGISTRY" "$detection_json" > "$selected_json" 2>/dev/null
  REG_EC=$?
  set -e
  if [ "$REG_EC" -eq 0 ] && [ -s "$selected_json" ]; then
    NSELECTED=$(python3 -c "import json; packs=json.load(open('$selected_json')); print(len(packs))")
    pass "$fixture_name: registry selected $NSELECTED pack(s)"
  else
    fail "$fixture_name: registry.py failed (exit $REG_EC) or produced empty output"
    return 1
  fi

  # Step 3: spine/run.sh (bash-4 gate)
  if [ "$BASH_GE4" = "false" ]; then
    skip "$fixture_name: spine invocation skipped -- bash ${BASH_VERSINFO[0]} < 4 (spine requires bash 4+; ubuntu CI will run this)"
    # Create an empty spine file so merge step is also skipped cleanly below
    printf '{"type":"provenance","tool":"ccgm-spine-skipped","version":"1.0"}\n' > "$spine_jsonl"
  else
    set +e
    bash "$SPINE" \
      --repo   "$repo_abs" \
      --tools  "$tools" \
      --output "$spine_jsonl" 2>/dev/null
    SPINE_EC=$?
    set -e
    if [ "$SPINE_EC" -eq 0 ] && [ -f "$spine_jsonl" ]; then
      pass "$fixture_name: spine/run.sh exited 0"
    else
      fail "$fixture_name: spine/run.sh failed (exit $SPINE_EC) or output missing"
      return 1
    fi
  fi

  # Step 4: merge-findings.py
  set +e
  python3 "$MERGE" \
    --spine  "$spine_jsonl" \
    --rubric "$RUBRIC" \
    --repo   "$repo_abs" \
    --output "$findings_jsonl" 2>/dev/null
  MERGE_EC=$?
  set -e
  if [ "$MERGE_EC" -eq 0 ] && [ -f "$findings_jsonl" ]; then
    pass "$fixture_name: merge-findings.py exited 0"
  else
    fail "$fixture_name: merge-findings.py failed (exit $MERGE_EC) or output missing"
    return 1
  fi

  # Export paths for caller
  PIPE_DETECTION_JSON="$detection_json"
  PIPE_SELECTED_JSON="$selected_json"
  PIPE_SPINE_JSONL="$spine_jsonl"
  PIPE_FINDINGS_JSONL="$findings_jsonl"
}

# ---------------------------------------------------------------------------
# Helper: assert the critical secrets finding is present in findings.jsonl.
# Gated on both GITLEAKS_AVAILABLE and BASH_GE4.
# ---------------------------------------------------------------------------
assert_critical_finding() {
  local fixture_name="$1"
  local findings_jsonl="$2"
  local fake_key="$3"

  if [ "$BASH_GE4" = "false" ]; then
    skip "$fixture_name: gitleaks finding asserts skipped -- bash < 4 (spine not run)"
    return
  fi

  if [ "$GITLEAKS_AVAILABLE" = "false" ]; then
    skip "$fixture_name: gitleaks not installed -- critical-finding asserts skipped (SKIP, not FAIL)"
    return
  fi

  # Assert >= 1 finding with check_id=secrets/leaked-credential, source=tool, severity=critical
  CRITICAL_COUNT="$(python3 - "$findings_jsonl" << 'PYEOF'
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
    if "type" in rec:
        continue
    if (rec.get("check_id") == "secrets/leaked-credential"
            and rec.get("source") == "tool"
            and rec.get("severity") == "critical"):
        count += 1
print(count)
PYEOF
)"

  if [ "${CRITICAL_COUNT:-0}" -ge 1 ]; then
    pass "$fixture_name: findings.jsonl contains >= 1 secrets/leaked-credential (source=tool, severity=critical)"
  else
    fail "$fixture_name: expected >= 1 secrets/leaked-credential critical finding, got ${CRITICAL_COUNT:-0}"
  fi

  # Assert the assembled fake key does NOT appear verbatim in findings.jsonl (redaction held)
  if grep -qF "$fake_key" "$findings_jsonl" 2>/dev/null; then
    fail "$fixture_name: assembled fake key appears unredacted in findings.jsonl -- redaction failed"
  else
    pass "$fixture_name: assembled fake key NOT in findings.jsonl (redaction held)"
  fi
}

# ---------------------------------------------------------------------------
# Helper: assert a coverage_gap record exists in findings.jsonl for an
# absent tool (verifies the spine coverage-gap passthrough).
# Gated on BASH_GE4 (spine must have run).
# ---------------------------------------------------------------------------
assert_coverage_gap() {
  local fixture_name="$1"
  local findings_jsonl="$2"

  if [ "$BASH_GE4" = "false" ]; then
    skip "$fixture_name: coverage_gap assert skipped -- bash < 4 (spine not run)"
    return
  fi

  # Check for at least one coverage_gap record (tool absent = gap emitted by spine)
  GAP_COUNT="$(python3 - "$findings_jsonl" << 'PYEOF'
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
)"

  if [ "${GAP_COUNT:-0}" -ge 1 ]; then
    pass "$fixture_name: coverage_gap record present in findings.jsonl (absent tool noted)"
  else
    # The gitleaks tool IS available, so the only expected gaps are for absent tools.
    # If all smoke-requested tools are installed, this may legitimately be 0.
    # Rather than fail, note it as informational.
    skip "$fixture_name: coverage_gap count is 0 (all requested tools may be installed)"
  fi
}

# ---------------------------------------------------------------------------
# Smoke A: JS app fixture
# ---------------------------------------------------------------------------
echo "--- [A] Smoke: JS app (package.json + tsconfig.json + index.ts + config.ts) ---"

REPO_A="$(make_tmp)/js-app"
OUT_A="$(make_tmp)"

mkdir -p "$REPO_A"
git -C "$REPO_A" init -q
git -C "$REPO_A" config user.email "test@ccgm.test"
git -C "$REPO_A" config user.name "CCGMTest"
git -C "$REPO_A" config core.hooksPath /dev/null 2>/dev/null || true

# Plant fixture files
printf '{"name":"my-app","version":"1.0.0","dependencies":{}}\n' > "$REPO_A/package.json"
printf '{"compilerOptions":{"target":"es2020","module":"commonjs","strict":true}}\n' > "$REPO_A/tsconfig.json"
printf 'export const greeting = "hello";\n' > "$REPO_A/index.ts"

# Plant the secret in config.ts using python3 to avoid shell-expansion of the key
python3 - "$REPO_A/config.ts" "$FAKE_KEY" << 'PYEOF'
import sys
path, key = sys.argv[1], sys.argv[2]
with open(path, "w") as fh:
    fh.write("// Test fixture: intentionally planted credential for scanner validation\n")
    fh.write('export const AWS_ACCESS_KEY_ID = "' + key + '";\n')
PYEOF

git -C "$REPO_A" add -A
git -C "$REPO_A" commit -q -m "init js app fixture"

# Run pipeline (gitleaks is the sole tool for the smoke; semgrep for coverage-gap)
run_pipeline "smoke-A (JS)" "$REPO_A" "gitleaks,semgrep" "$OUT_A"

# Sanity: JS fixture selects language:javascript packs
SELECTED_A_IDS="$(python3 - "$OUT_A/selected.json" << 'PYEOF'
import json, sys
packs = json.load(open(sys.argv[1]))
ids = sorted(p["id"] for p in packs)
print(",".join(ids))
PYEOF
)"

if echo "$SELECTED_A_IDS" | grep -q "ccgm/secrets"; then
  pass "smoke-A: registry selected ccgm/secrets (always pack)"
else
  fail "smoke-A: registry did not select ccgm/secrets (expected for JS fixture)"
fi

# JS-gated packs must be present: at least ccgm/typescript-react or ccgm/accessibility
if echo "$SELECTED_A_IDS" | grep -qE "ccgm/typescript-react|ccgm/accessibility"; then
  pass "smoke-A: registry selected at least one language:javascript-gated pack"
else
  fail "smoke-A: no language:javascript-gated packs selected (expected for JS+TS fixture)"
fi

assert_critical_finding "smoke-A" "$OUT_A/findings.jsonl" "$FAKE_KEY"
assert_coverage_gap "smoke-A" "$OUT_A/findings.jsonl"

# ---------------------------------------------------------------------------
# Smoke B: Go service fixture
# ---------------------------------------------------------------------------
echo ""
echo "--- [B] Smoke: Go service (go.mod + main.go + config.go) ---"

REPO_B="$(make_tmp)/go-service"
OUT_B="$(make_tmp)"

mkdir -p "$REPO_B"
git -C "$REPO_B" init -q
git -C "$REPO_B" config user.email "test@ccgm.test"
git -C "$REPO_B" config user.name "CCGMTest"
git -C "$REPO_B" config core.hooksPath /dev/null 2>/dev/null || true

printf 'module example.com/myservice\n\ngo 1.21\n' > "$REPO_B/go.mod"
printf 'package main\n\nfunc main() {}\n' > "$REPO_B/main.go"

# Plant the secret in config.go
python3 - "$REPO_B/config.go" "$FAKE_KEY" << 'PYEOF'
import sys
path, key = sys.argv[1], sys.argv[2]
with open(path, "w") as fh:
    fh.write("package main\n\n")
    fh.write("// Test fixture: intentionally planted credential for scanner validation\n")
    fh.write('const AWSAccessKeyID = "' + key + '"\n')
PYEOF

git -C "$REPO_B" add -A
git -C "$REPO_B" commit -q -m "init go service fixture"

run_pipeline "smoke-B (Go)" "$REPO_B" "gitleaks,semgrep" "$OUT_B"

# Sanity: Go fixture should NOT select JS-gated packs
SELECTED_B_IDS="$(python3 - "$OUT_B/selected.json" << 'PYEOF'
import json, sys
packs = json.load(open(sys.argv[1]))
ids = sorted(p["id"] for p in packs)
print(",".join(ids))
PYEOF
)"

if echo "$SELECTED_B_IDS" | grep -q "ccgm/secrets"; then
  pass "smoke-B: registry selected ccgm/secrets (always pack)"
else
  fail "smoke-B: registry did not select ccgm/secrets"
fi

# Go fixture must NOT select JS-only packs (typescript-react is JS-gated)
if echo "$SELECTED_B_IDS" | grep -q "ccgm/typescript-react"; then
  fail "smoke-B: registry selected ccgm/typescript-react for a Go-only fixture (unexpected)"
else
  pass "smoke-B: registry did not select JS-gated pack ccgm/typescript-react (correct for Go fixture)"
fi

assert_critical_finding "smoke-B" "$OUT_B/findings.jsonl" "$FAKE_KEY"
assert_coverage_gap "smoke-B" "$OUT_B/findings.jsonl"

# ---------------------------------------------------------------------------
# Smoke C: migrations repo fixture
# ---------------------------------------------------------------------------
echo ""
echo "--- [C] Smoke: migrations repo (package.json + supabase/migrations/ + secret) ---"

REPO_C="$(make_tmp)/migrations-repo"
OUT_C="$(make_tmp)"

mkdir -p "$REPO_C/supabase/migrations"
git -C "$REPO_C" init -q
git -C "$REPO_C" config user.email "test@ccgm.test"
git -C "$REPO_C" config user.name "CCGMTest"
git -C "$REPO_C" config core.hooksPath /dev/null 2>/dev/null || true

printf '{"name":"migrations-app","version":"1.0.0"}\n' > "$REPO_C/package.json"
python3 - "$REPO_C/supabase/migrations/0001_init.sql" << 'PYEOF'
import sys
with open(sys.argv[1], "w") as fh:
    fh.write("-- init\n")
    fh.write("CREATE TABLE users (id serial PRIMARY KEY, name text);\n")
PYEOF

# Plant the secret in a credentials file
python3 - "$REPO_C/secrets.env" "$FAKE_KEY" << 'PYEOF'
import sys
path, key = sys.argv[1], sys.argv[2]
with open(path, "w") as fh:
    fh.write("# Test fixture: intentionally planted credential for scanner validation\n")
    fh.write("AWS_ACCESS_KEY_ID=" + key + "\n")
PYEOF

git -C "$REPO_C" add -A
git -C "$REPO_C" commit -q -m "init migrations repo fixture"

run_pipeline "smoke-C (migrations)" "$REPO_C" "gitleaks,squawk" "$OUT_C"

# Sanity: migrations fixture must select ccgm/data-migrations (has_migrations=true)
SELECTED_C_IDS="$(python3 - "$OUT_C/selected.json" << 'PYEOF'
import json, sys
packs = json.load(open(sys.argv[1]))
ids = sorted(p["id"] for p in packs)
print(",".join(ids))
PYEOF
)"

if echo "$SELECTED_C_IDS" | grep -q "ccgm/data-migrations"; then
  pass "smoke-C: registry selected ccgm/data-migrations (has_migrations pack)"
else
  fail "smoke-C: registry did not select ccgm/data-migrations (expected for supabase/migrations/ fixture)"
fi

if echo "$SELECTED_C_IDS" | grep -q "ccgm/secrets"; then
  pass "smoke-C: registry selected ccgm/secrets (always pack)"
else
  fail "smoke-C: registry did not select ccgm/secrets"
fi

assert_critical_finding "smoke-C" "$OUT_C/findings.jsonl" "$FAKE_KEY"
assert_coverage_gap "smoke-C" "$OUT_C/findings.jsonl"

# ---------------------------------------------------------------------------
# ADV-009 self-check: this test file must not contain the assembled AKIA key
# ---------------------------------------------------------------------------
echo ""
echo "--- ADV-009 self-check ---"

SELF="$SCRIPT_DIR/test-smoke-audits.sh"
SELF_GREP="$(grep -cE 'AKIA[A-Z0-9]{12,}' "$SELF" 2>/dev/null || true)"
if [ "${SELF_GREP:-0}" -eq 0 ]; then
  pass "ADV-009: grep -nE 'AKIA[A-Z0-9]{12,}' is empty in this test file"
else
  fail "ADV-009: assembled AKIA key pattern found ${SELF_GREP} time(s) -- violates ADV-009"
fi

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
echo ""
echo "=== Results: $PASS passed, $FAIL failed, $SKIP skipped ==="

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
