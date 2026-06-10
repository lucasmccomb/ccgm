#!/usr/bin/env bash
# CCGM audit -- test-provenance.sh
# Tests for Epic 3.4: provenance.py (audit_provenance header + CODEOWNERS tagging +
# per-package scoping).
#
# Usage: bash modules/commands-extra/skills/audit/tests/test-provenance.sh
# Exit:  0 = all tests passed, non-zero = at least one failure

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROV_SCRIPT="$SCRIPT_DIR/../scripts/provenance.py"
RUBRIC_FILE="$SCRIPT_DIR/../schemas/severity-rubric.json"

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

# Extract value for a top-level key from the first line of a JSONL file.
# Usage: jsonl_header_field <file> <key>
jsonl_header_field() {
  python3 - "$1" "$2" << 'PYEOF'
import json, sys
with open(sys.argv[1]) as fh:
    line = fh.readline().strip()
obj = json.loads(line)
val = obj.get(sys.argv[2], "")
if isinstance(val, dict):
    print(json.dumps(val))
elif isinstance(val, list):
    print(json.dumps(val))
else:
    print(val)
PYEOF
}

# Return the value of properties.owner for the first non-type-record whose
# location.path matches the given path.
# Usage: finding_owner <file> <path>
finding_owner() {
  python3 - "$1" "$2" << 'PYEOF'
import json, sys
with open(sys.argv[1]) as fh:
    for line in fh:
        line = line.strip()
        if not line:
            continue
        obj = json.loads(line)
        if "type" in obj:
            continue
        loc = obj.get("location", {})
        if loc.get("path") == sys.argv[2]:
            owner = (obj.get("properties") or {}).get("owner", "")
            if isinstance(owner, list):
                print(",".join(owner))
            else:
                print(owner)
            sys.exit(0)
print("")
PYEOF
}

# Return the value of properties.package for the first non-type-record whose
# location.path matches the given path.
# Usage: finding_package <file> <path>
finding_package() {
  python3 - "$1" "$2" << 'PYEOF'
import json, sys
with open(sys.argv[1]) as fh:
    for line in fh:
        line = line.strip()
        if not line:
            continue
        obj = json.loads(line)
        if "type" in obj:
            continue
        loc = obj.get("location", {})
        if loc.get("path") == sys.argv[2]:
            pkg = (obj.get("properties") or {}).get("package", "")
            print(pkg)
            sys.exit(0)
print("")
PYEOF
}

# Count records of a given type in a JSONL file.
# Usage: count_type <file> <type>
count_type() {
  python3 - "$1" "$2" << 'PYEOF'
import json, sys
count = 0
with open(sys.argv[1]) as fh:
    for line in fh:
        line = line.strip()
        if not line:
            continue
        obj = json.loads(line)
        if obj.get("type") == sys.argv[2]:
            count += 1
print(count)
PYEOF
}

# ---------------------------------------------------------------------------
# Minimal finding fixture (no external tool deps)
# ---------------------------------------------------------------------------

make_finding() {
  local path="$1"
  python3 - "$path" << 'PYEOF'
import json, sys
print(json.dumps({
    "check_id": "security/hardcoded-secret",
    "rule_id": "gitleaks/generic-api-key",
    "severity": "high",
    "confidence": "high",
    "location": {"path": sys.argv[1], "line": 10},
    "message": "Hardcoded secret detected",
    "fingerprint": "aaaaaaaaaaaaaaaa",
    "detection": "tool",
    "source": "tool",
    "properties": {}
}))
PYEOF
}

# ---------------------------------------------------------------------------
# Scenario A: audit_provenance header fields populated
# ---------------------------------------------------------------------------

run_scenario_a() {
  local tmpdir
  tmpdir="$(mktemp -d /tmp/ccgm-test-provenance-XXXXXX)"
  trap "rm -rf '$tmpdir'" RETURN

  # Create a minimal git repo so git rev-parse HEAD returns a real SHA
  git -C "$tmpdir" init -q
  git -C "$tmpdir" -c core.hooksPath=/dev/null \
      -c user.email="test@test.invalid" \
      -c user.name="Test" \
      commit --allow-empty -m "init" -q

  local expected_sha
  expected_sha="$(git -C "$tmpdir" rev-parse HEAD)"

  # Build a minimal findings.jsonl
  local findings_file="$tmpdir/findings.jsonl"
  make_finding "src/app.ts" > "$findings_file"

  local out_file="$tmpdir/out.jsonl"

  python3 "$PROV_SCRIPT" \
    --findings "$findings_file" \
    --repo "$tmpdir" \
    --rubric "$RUBRIC_FILE" \
    --model "test-model-x" \
    --optional-check "security/extra-check" \
    --skip-tool-versions \
    --output "$out_file"

  # Verify header is first line and type is correct
  local record_type
  record_type="$(jsonl_header_field "$out_file" type)"
  if [[ "$record_type" == "audit_provenance" ]]; then
    pass "scenario-a: header type=audit_provenance"
  else
    fail "scenario-a: expected type=audit_provenance, got '$record_type'"
  fi

  # commit matches real SHA
  local got_commit
  got_commit="$(jsonl_header_field "$out_file" commit)"
  if [[ "$got_commit" == "$expected_sha" ]]; then
    pass "scenario-a: commit matches git HEAD SHA"
  else
    fail "scenario-a: expected commit='$expected_sha', got '$got_commit'"
  fi

  # rubric_version comes from rubric file
  local expected_rubric_ver
  expected_rubric_ver="$(python3 -c "import json; d=json.load(open('$RUBRIC_FILE')); print(d.get('version','unknown'))")"
  local got_rubric_ver
  got_rubric_ver="$(jsonl_header_field "$out_file" rubric_version)"
  if [[ "$got_rubric_ver" == "$expected_rubric_ver" ]]; then
    pass "scenario-a: rubric_version='$got_rubric_ver'"
  else
    fail "scenario-a: expected rubric_version='$expected_rubric_ver', got '$got_rubric_ver'"
  fi

  # model matches --model arg
  local got_model
  got_model="$(jsonl_header_field "$out_file" model)"
  if [[ "$got_model" == "test-model-x" ]]; then
    pass "scenario-a: model='test-model-x'"
  else
    fail "scenario-a: expected model='test-model-x', got '$got_model'"
  fi

  # optional_checks_ran contains the passed check id
  local got_opts
  got_opts="$(jsonl_header_field "$out_file" optional_checks_ran)"
  if echo "$got_opts" | grep -q "security/extra-check"; then
    pass "scenario-a: optional_checks_ran contains passed id"
  else
    fail "scenario-a: optional_checks_ran='$got_opts' missing 'security/extra-check'"
  fi

  # tool_versions is {} when --skip-tool-versions
  local got_tv
  got_tv="$(jsonl_header_field "$out_file" tool_versions)"
  if [[ "$got_tv" == "{}" ]]; then
    pass "scenario-a: tool_versions={} with --skip-tool-versions"
  else
    fail "scenario-a: expected tool_versions={}, got '$got_tv'"
  fi

  # skill_version matches the version field in module.json
  local module_json="$SCRIPT_DIR/../../../module.json"
  local expected_sv
  expected_sv="$(python3 -c "import json; d=json.load(open('$module_json')); print(d.get('version',''))")"
  local got_sv
  got_sv="$(jsonl_header_field "$out_file" skill_version)"
  if [[ -n "$expected_sv" && "$got_sv" == "$expected_sv" ]]; then
    pass "scenario-a: skill_version='$got_sv' matches module.json version"
  else
    fail "scenario-a: expected skill_version='$expected_sv', got '$got_sv'"
  fi
}

# ---------------------------------------------------------------------------
# Scenario B: CODEOWNERS owner tagging — last-match-wins
# ---------------------------------------------------------------------------

run_scenario_b() {
  local tmpdir
  tmpdir="$(mktemp -d /tmp/ccgm-test-provenance-XXXXXX)"
  trap "rm -rf '$tmpdir'" RETURN

  # Create a git repo
  git -C "$tmpdir" init -q
  git -C "$tmpdir" -c core.hooksPath=/dev/null \
      -c user.email="test@test.invalid" \
      -c user.name="Test" \
      commit --allow-empty -m "init" -q

  # Write CODEOWNERS
  mkdir -p "$tmpdir/.github"
  cat > "$tmpdir/.github/CODEOWNERS" << 'EOF'
# Global owner
* @default-owner

# Backend overrides global for src/
src/ @backend-team

# The auth subdirectory has a more specific owner — should win over src/
src/auth/ @auth-team
EOF

  # Two findings: one in src/auth/ and one in src/api/
  {
    make_finding "src/auth/session.ts"
    make_finding "src/api/routes.ts"
    make_finding "docs/README.md"
  } > "$tmpdir/findings.jsonl"

  local out_file="$tmpdir/out.jsonl"

  python3 "$PROV_SCRIPT" \
    --findings "$tmpdir/findings.jsonl" \
    --repo "$tmpdir" \
    --rubric "$RUBRIC_FILE" \
    --skip-tool-versions \
    --output "$out_file"

  # src/auth/session.ts -> last-match-wins: src/auth/ rule -> @auth-team
  local auth_owner
  auth_owner="$(finding_owner "$out_file" "src/auth/session.ts")"
  if [[ "$auth_owner" == "@auth-team" ]]; then
    pass "scenario-b: src/auth/ finding tagged @auth-team (last-match-wins)"
  else
    fail "scenario-b: expected @auth-team for src/auth/, got '$auth_owner'"
  fi

  # src/api/routes.ts -> matches src/ rule -> @backend-team
  local api_owner
  api_owner="$(finding_owner "$out_file" "src/api/routes.ts")"
  if [[ "$api_owner" == "@backend-team" ]]; then
    pass "scenario-b: src/api/ finding tagged @backend-team"
  else
    fail "scenario-b: expected @backend-team for src/api/, got '$api_owner'"
  fi

  # docs/README.md -> matches only * -> @default-owner
  local docs_owner
  docs_owner="$(finding_owner "$out_file" "docs/README.md")"
  if [[ "$docs_owner" == "@default-owner" ]]; then
    pass "scenario-b: docs/ finding tagged @default-owner (catch-all)"
  else
    fail "scenario-b: expected @default-owner for docs/, got '$docs_owner'"
  fi
}

# ---------------------------------------------------------------------------
# Scenario C: per-package monorepo scoping + package_summary records
# ---------------------------------------------------------------------------

run_scenario_c() {
  local tmpdir
  tmpdir="$(mktemp -d /tmp/ccgm-test-provenance-XXXXXX)"
  trap "rm -rf '$tmpdir'" RETURN

  # Create a git repo
  git -C "$tmpdir" init -q
  git -C "$tmpdir" -c core.hooksPath=/dev/null \
      -c user.email="test@test.invalid" \
      -c user.name="Test" \
      commit --allow-empty -m "init" -q

  # Create two package directories
  mkdir -p "$tmpdir/packages/auth" "$tmpdir/packages/api"

  # Write pnpm-workspace.yaml
  cat > "$tmpdir/pnpm-workspace.yaml" << 'EOF'
packages:
  - "packages/*"
EOF

  # Findings in each package and one outside
  {
    make_finding "packages/auth/src/login.ts"
    make_finding "packages/auth/src/token.ts"
    make_finding "packages/api/routes/users.ts"
    make_finding "scripts/deploy.sh"
  } > "$tmpdir/findings.jsonl"

  local out_file="$tmpdir/out.jsonl"

  python3 "$PROV_SCRIPT" \
    --findings "$tmpdir/findings.jsonl" \
    --repo "$tmpdir" \
    --rubric "$RUBRIC_FILE" \
    --skip-tool-versions \
    --output "$out_file"

  # Check properties.package for auth finding
  local auth_pkg
  auth_pkg="$(finding_package "$out_file" "packages/auth/src/login.ts")"
  if [[ "$auth_pkg" == "packages/auth" ]]; then
    pass "scenario-c: packages/auth finding tagged packages/auth"
  else
    fail "scenario-c: expected packages/auth, got '$auth_pkg'"
  fi

  # Check properties.package for api finding
  local api_pkg
  api_pkg="$(finding_package "$out_file" "packages/api/routes/users.ts")"
  if [[ "$api_pkg" == "packages/api" ]]; then
    pass "scenario-c: packages/api finding tagged packages/api"
  else
    fail "scenario-c: expected packages/api, got '$api_pkg'"
  fi

  # scripts/deploy.sh is not in any package root — should have no package property
  local no_pkg
  no_pkg="$(finding_package "$out_file" "scripts/deploy.sh")"
  if [[ -z "$no_pkg" ]]; then
    pass "scenario-c: scripts/ finding has no package tag"
  else
    fail "scenario-c: scripts/ finding should have no package, got '$no_pkg'"
  fi

  # Count package_summary records: expect 2 (one per detected package with findings)
  local summary_count
  summary_count="$(count_type "$out_file" package_summary)"
  if [[ "$summary_count" -ge 2 ]]; then
    pass "scenario-c: $summary_count package_summary record(s) emitted"
  else
    fail "scenario-c: expected >=2 package_summary records, got $summary_count"
  fi

  # Verify counts for packages/auth: 2 high findings
  local auth_counts
  auth_counts="$(python3 - "$out_file" << 'PYEOF'
import json, sys
with open(sys.argv[1]) as fh:
    for line in fh:
        line = line.strip()
        if not line:
            continue
        obj = json.loads(line)
        if obj.get("type") == "package_summary" and obj.get("package") == "packages/auth":
            print(obj["counts"].get("high", 0))
            break
PYEOF
)"
  if [[ "$auth_counts" -eq 2 ]]; then
    pass "scenario-c: packages/auth summary shows 2 high findings"
  else
    fail "scenario-c: expected packages/auth high=2, got '$auth_counts'"
  fi
}


# ---------------------------------------------------------------------------
# Scenario D: live tool_versions — gitleaks key present when installed
# ---------------------------------------------------------------------------

run_scenario_d() {
  if ! command -v gitleaks > /dev/null 2>&1; then
    printf '  [SKIP] scenario-d: gitleaks not on PATH\n'
    return
  fi

  local tmpdir
  tmpdir="$(mktemp -d /tmp/ccgm-test-provenance-XXXXXX)"
  trap "rm -rf '$tmpdir'" RETURN

  git -C "$tmpdir" init -q
  git -C "$tmpdir" -c core.hooksPath=/dev/null \
      -c user.email="test@test.invalid" \
      -c user.name="Test" \
      commit --allow-empty -m "init" -q

  local findings_file="$tmpdir/findings.jsonl"
  make_finding "src/app.ts" > "$findings_file"

  local out_file="$tmpdir/out.jsonl"

  # Run WITHOUT --skip-tool-versions so tool_versions is populated
  python3 "$PROV_SCRIPT" \
    --findings "$findings_file" \
    --repo "$tmpdir" \
    --rubric "$RUBRIC_FILE" \
    --output "$out_file"

  local got_tv
  got_tv="$(jsonl_header_field "$out_file" tool_versions)"

  # tool_versions must not be empty object when gitleaks is installed
  if [[ "$got_tv" == "{}" ]]; then
    fail "scenario-d: tool_versions={} but gitleaks is installed; expected gitleaks key"
    return
  fi

  # gitleaks key must be present
  local has_gitleaks
  has_gitleaks="$(python3 -c "import json,sys; d=json.loads(sys.argv[1]); print('yes' if 'gitleaks' in d else 'no')" "$got_tv")"
  if [[ "$has_gitleaks" != "yes" ]]; then
    fail "scenario-d: tool_versions missing gitleaks key; got: $got_tv"
    return
  fi

  # gitleaks version string must be non-empty
  local gitleaks_ver
  gitleaks_ver="$(python3 -c "import json,sys; d=json.loads(sys.argv[1]); print(d.get('gitleaks',''))" "$got_tv")"
  if [[ -z "$gitleaks_ver" ]]; then
    fail "scenario-d: gitleaks version string is empty"
    return
  fi

  pass "scenario-d: tool_versions contains gitleaks='$gitleaks_ver' (live probe)"
}

# ---------------------------------------------------------------------------
# Scenario E: CODEOWNERS directory-prefix matching without trailing slash
# ---------------------------------------------------------------------------

run_scenario_e() {
  local tmpdir
  tmpdir="$(mktemp -d /tmp/ccgm-test-provenance-XXXXXX)"
  trap "rm -rf '$tmpdir'" RETURN

  git -C "$tmpdir" init -q
  git -C "$tmpdir" -c core.hooksPath=/dev/null \
      -c user.email="test@test.invalid" \
      -c user.name="Test" \
      commit --allow-empty -m "init" -q

  # "apps/web" without trailing slash — GitHub treats this as a directory prefix
  mkdir -p "$tmpdir/.github"
  cat > "$tmpdir/.github/CODEOWNERS" << 'EOF'
* @default-owner
apps/web @web-team
EOF

  {
    make_finding "apps/web/x.ts"
    make_finding "apps/web/nested/y.ts"
    make_finding "apps/other/z.ts"
  } > "$tmpdir/findings.jsonl"

  local out_file="$tmpdir/out.jsonl"

  python3 "$PROV_SCRIPT" \
    --findings "$tmpdir/findings.jsonl" \
    --repo "$tmpdir" \
    --rubric "$RUBRIC_FILE" \
    --skip-tool-versions \
    --output "$out_file"

  # apps/web/x.ts must be tagged @web-team (direct child)
  local owner_direct
  owner_direct="$(finding_owner "$out_file" "apps/web/x.ts")"
  if [[ "$owner_direct" == "@web-team" ]]; then
    pass "scenario-e: apps/web/x.ts tagged @web-team (no-trailing-slash dir pattern)"
  else
    fail "scenario-e: expected @web-team for apps/web/x.ts, got '$owner_direct'"
  fi

  # apps/web/nested/y.ts must also be tagged @web-team (deeper child)
  local owner_nested
  owner_nested="$(finding_owner "$out_file" "apps/web/nested/y.ts")"
  if [[ "$owner_nested" == "@web-team" ]]; then
    pass "scenario-e: apps/web/nested/y.ts tagged @web-team (nested child)"
  else
    fail "scenario-e: expected @web-team for apps/web/nested/y.ts, got '$owner_nested'"
  fi

  # apps/other/z.ts must fall through to @default-owner (not prefixed by apps/web)
  local owner_other
  owner_other="$(finding_owner "$out_file" "apps/other/z.ts")"
  if [[ "$owner_other" == "@default-owner" ]]; then
    pass "scenario-e: apps/other/z.ts tagged @default-owner (not under apps/web)"
  else
    fail "scenario-e: expected @default-owner for apps/other/z.ts, got '$owner_other'"
  fi
}

# ---------------------------------------------------------------------------
# Run all scenarios
# ---------------------------------------------------------------------------

printf '\n=== test-provenance.sh ===\n'

printf '\nScenario A: audit_provenance header fields\n'
run_scenario_a

printf '\nScenario B: CODEOWNERS last-match-wins owner tagging\n'
run_scenario_b

printf '\nScenario C: per-package scoping + package_summary records\n'
run_scenario_c

printf '\nScenario D: live tool_versions — gitleaks key\n'
run_scenario_d

printf '\nScenario E: CODEOWNERS directory-prefix matching (no trailing slash)\n'
run_scenario_e

# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

printf '\n--- Summary ---\n'
printf 'PASS: %d  FAIL: %d\n' "$PASS" "$FAIL"
if [[ "$FAIL" -gt 0 ]]; then
  printf 'FAILURES:\n'
  for e in "${ERRORS[@]}"; do
    printf '  - %s\n' "$e"
  done
  exit 1
fi
exit 0
