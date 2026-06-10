#!/usr/bin/env bash
# test-detect-ecosystems.sh
# Tests for Epic 1.3: Phase-0 ecosystem + project-shape + tool detector
#
# Fixtures:
#   - JS repo (package.json)
#   - Go repo (go.mod)
#   - Python repo (requirements.txt)
#   - Repo with supabase/migrations/ directory
#   - Browser extension (manifest.json with manifest_version)
#
# Usage: bash modules/commands-extra/skills/audit/tests/test-detect-ecosystems.sh
# Exit:  0 = all pass, non-zero = at least one failure

set -euo pipefail

PASS_COUNT=0
FAIL_COUNT=0
FAILURES=()

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
DETECT_SCRIPT="$SCRIPT_DIR/../scripts/detect-ecosystems.sh"

# Verify the detector exists before attempting tests
if [ ! -f "$DETECT_SCRIPT" ]; then
  echo "ERROR: detector script not found at: $DETECT_SCRIPT" >&2
  exit 1
fi

# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------

pass() {
  local name="$1"
  echo "  PASS: $name"
  PASS_COUNT=$((PASS_COUNT + 1))
}

fail() {
  local name="$1"
  local detail="${2:-}"
  echo "  FAIL: $name${detail:+ — $detail}"
  FAIL_COUNT=$((FAIL_COUNT + 1))
  FAILURES+=("$name${detail:+: $detail}")
}

# Run the detector on a directory and capture output
run_detector() {
  bash "$DETECT_SCRIPT" "$1"
}

# Assert a JSON array field contains a specific value
assert_contains() {
  local name="$1"
  local json="$2"
  local field="$3"
  local value="$4"
  if echo "$json" | jq -e --arg v "$value" "$field | index(\$v) != null" >/dev/null 2>&1; then
    pass "$name"
  else
    actual=$(echo "$json" | jq -r "$field" 2>/dev/null || echo "(parse error)")
    fail "$name" "expected '$value' in $field, got: $actual"
  fi
}

# Assert a JSON array field does NOT contain a specific value
assert_not_contains() {
  local name="$1"
  local json="$2"
  local field="$3"
  local value="$4"
  if echo "$json" | jq -e --arg v "$value" "$field | index(\$v) == null" >/dev/null 2>&1; then
    pass "$name"
  else
    fail "$name" "expected '$value' NOT in $field, but it was present"
  fi
}

# Assert a JSON boolean field equals expected value (true/false)
assert_bool() {
  local name="$1"
  local json="$2"
  local field="$3"
  local expected="$4"  # "true" or "false"
  actual=$(echo "$json" | jq -r "$field" 2>/dev/null || echo "parse_error")
  if [ "$actual" = "$expected" ]; then
    pass "$name"
  else
    fail "$name" "expected $field=$expected, got $actual"
  fi
}

# Assert a JSON array field is empty
assert_empty_array() {
  local name="$1"
  local json="$2"
  local field="$3"
  count=$(echo "$json" | jq -r "$field | length" 2>/dev/null || echo "-1")
  if [ "$count" = "0" ]; then
    pass "$name"
  else
    fail "$name" "expected empty array for $field, got length=$count"
  fi
}

# ---------------------------------------------------------------------------
# Create temp fixtures
# ---------------------------------------------------------------------------
TMPDIR_ROOT=$(mktemp -d)
trap 'rm -rf "$TMPDIR_ROOT"' EXIT

# Each fixture is a plain directory (not a git repo) — pass as explicit TARGET_DIR
make_fixture() {
  local name="$1"
  local dir="$TMPDIR_ROOT/$name"
  mkdir -p "$dir"
  echo "$dir"
}

# ---------------------------------------------------------------------------
# Fixture 1: JavaScript repo
# ---------------------------------------------------------------------------
echo ""
echo "=== Fixture: JavaScript repo ==="
FIX_JS=$(make_fixture "js-repo")
cat > "$FIX_JS/package.json" <<'JSON'
{
  "name": "my-app",
  "version": "1.0.0",
  "dependencies": {
    "react": "^18.0.0",
    "express": "^4.18.0"
  }
}
JSON

JS_JSON=$(run_detector "$FIX_JS")
assert_contains     "js: detected javascript"    "$JS_JSON" ".detected_ecosystems" "javascript"
assert_not_contains "js: no go ecosystem"        "$JS_JSON" ".detected_ecosystems" "go"
assert_not_contains "js: no python ecosystem"    "$JS_JSON" ".detected_ecosystems" "python"
assert_bool         "js: no migrations"          "$JS_JSON" ".project_shape.has_migrations" "false"
assert_bool         "js: no dockerfile"          "$JS_JSON" ".project_shape.has_dockerfile" "false"
assert_bool         "js: no workflows"           "$JS_JSON" ".project_shape.has_workflows"  "false"
assert_bool         "js: not extension"          "$JS_JSON" ".project_shape.is_extension"   "false"
assert_bool         "js: not mobile"             "$JS_JSON" ".project_shape.is_mobile"      "false"
assert_contains     "js: react framework"        "$JS_JSON" ".project_shape.frameworks" "react"
assert_contains     "js: express framework"      "$JS_JSON" ".project_shape.frameworks" "express"

# ---------------------------------------------------------------------------
# Fixture 2: Go repo
# ---------------------------------------------------------------------------
echo ""
echo "=== Fixture: Go repo ==="
FIX_GO=$(make_fixture "go-repo")
cat > "$FIX_GO/go.mod" <<'GOMOD'
module github.com/example/myapp

go 1.21
GOMOD

GO_JSON=$(run_detector "$FIX_GO")
assert_contains     "go: detected go"         "$GO_JSON" ".detected_ecosystems" "go"
assert_not_contains "go: no javascript"       "$GO_JSON" ".detected_ecosystems" "javascript"
assert_not_contains "go: no python"           "$GO_JSON" ".detected_ecosystems" "python"
assert_bool         "go: no migrations"       "$GO_JSON" ".project_shape.has_migrations" "false"
assert_bool         "go: no dockerfile"       "$GO_JSON" ".project_shape.has_dockerfile" "false"

# ---------------------------------------------------------------------------
# Fixture 3: Python repo
# ---------------------------------------------------------------------------
echo ""
echo "=== Fixture: Python repo ==="
FIX_PY=$(make_fixture "py-repo")
cat > "$FIX_PY/requirements.txt" <<'TXT'
flask>=2.3.0
requests>=2.28.0
TXT

PY_JSON=$(run_detector "$FIX_PY")
assert_contains     "py: detected python"     "$PY_JSON" ".detected_ecosystems" "python"
assert_not_contains "py: no javascript"       "$PY_JSON" ".detected_ecosystems" "javascript"
assert_not_contains "py: no go"               "$PY_JSON" ".detected_ecosystems" "go"
assert_bool         "py: no migrations"       "$PY_JSON" ".project_shape.has_migrations" "false"
assert_bool         "py: no dockerfile"       "$PY_JSON" ".project_shape.has_dockerfile" "false"

# ---------------------------------------------------------------------------
# Fixture 4: Repo with supabase/migrations/
# ---------------------------------------------------------------------------
echo ""
echo "=== Fixture: supabase/migrations ==="
FIX_SQL=$(make_fixture "sql-repo")
mkdir -p "$FIX_SQL/supabase/migrations"
cat > "$FIX_SQL/supabase/migrations/20240101_init.sql" <<'SQL'
CREATE TABLE users (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  email text NOT NULL UNIQUE
);
SQL

SQL_JSON=$(run_detector "$FIX_SQL")
assert_contains     "sql: detected sql"           "$SQL_JSON" ".detected_ecosystems" "sql"
assert_bool         "sql: has_migrations true"    "$SQL_JSON" ".project_shape.has_migrations" "true"
assert_bool         "sql: no dockerfile"          "$SQL_JSON" ".project_shape.has_dockerfile" "false"
assert_bool         "sql: not extension"          "$SQL_JSON" ".project_shape.is_extension"   "false"

# ---------------------------------------------------------------------------
# Fixture 5: Browser extension (manifest.json with manifest_version)
# ---------------------------------------------------------------------------
echo ""
echo "=== Fixture: Browser extension ==="
FIX_EXT=$(make_fixture "ext-repo")
cat > "$FIX_EXT/manifest.json" <<'JSON'
{
  "manifest_version": 3,
  "name": "My Extension",
  "version": "1.0.0",
  "description": "A test browser extension"
}
JSON
cat > "$FIX_EXT/package.json" <<'JSON'
{
  "name": "my-extension",
  "version": "1.0.0"
}
JSON

EXT_JSON=$(run_detector "$FIX_EXT")
assert_bool         "ext: is_extension true"      "$EXT_JSON" ".project_shape.is_extension"   "true"
assert_contains     "ext: detected javascript"    "$EXT_JSON" ".detected_ecosystems" "javascript"

# ---------------------------------------------------------------------------
# Fixture 6: manifest.json WITHOUT manifest_version (NOT an extension)
# ---------------------------------------------------------------------------
echo ""
echo "=== Fixture: manifest.json (not an extension) ==="
FIX_NOEXT=$(make_fixture "noext-repo")
cat > "$FIX_NOEXT/manifest.json" <<'JSON'
{
  "name": "some-config",
  "version": "1.0.0"
}
JSON

NOEXT_JSON=$(run_detector "$FIX_NOEXT")
assert_bool         "noext: is_extension false"   "$NOEXT_JSON" ".project_shape.is_extension" "false"

# ---------------------------------------------------------------------------
# Fixture 7: Repo with Dockerfile → has_dockerfile=true
# ---------------------------------------------------------------------------
echo ""
echo "=== Fixture: Dockerfile ==="
FIX_DOCK=$(make_fixture "docker-repo")
cat > "$FIX_DOCK/Dockerfile" <<'EOF'
FROM node:20-alpine
WORKDIR /app
COPY . .
RUN npm install
CMD ["node", "index.js"]
EOF

DOCK_JSON=$(run_detector "$FIX_DOCK")
assert_bool         "docker: has_dockerfile true" "$DOCK_JSON" ".project_shape.has_dockerfile" "true"
assert_contains     "docker: detected docker"     "$DOCK_JSON" ".detected_ecosystems" "docker"

# ---------------------------------------------------------------------------
# Fixture 8: Repo with .github/workflows/ → has_workflows=true
# ---------------------------------------------------------------------------
echo ""
echo "=== Fixture: .github/workflows ==="
FIX_GHA=$(make_fixture "gha-repo")
mkdir -p "$FIX_GHA/.github/workflows"
cat > "$FIX_GHA/.github/workflows/ci.yml" <<'YAML'
name: CI
on: [push]
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
YAML

GHA_JSON=$(run_detector "$FIX_GHA")
assert_bool         "gha: has_workflows true"     "$GHA_JSON" ".project_shape.has_workflows" "true"

# ---------------------------------------------------------------------------
# available_tools: reflects real command -v results
# ---------------------------------------------------------------------------
echo ""
echo "=== available_tools accuracy ==="
FIX_TOOLS=$(make_fixture "tools-check")
TOOLS_JSON=$(run_detector "$FIX_TOOLS")

# jq is always available (we depend on it) — must appear in available_tools
assert_contains "tools: jq present" "$TOOLS_JSON" ".available_tools" "jq"

# python3 is always available (used by the script itself)
assert_contains "tools: python3 present" "$TOOLS_JSON" ".available_tools" "python3"

# Cross-check: every tool in available_tools must pass command -v
tools_list=$(echo "$TOOLS_JSON" | jq -r '.available_tools[]' 2>/dev/null || true)
tool_check_fail=0
if [ -n "$tools_list" ]; then
  while IFS= read -r tool; do
    [ -z "$tool" ] && continue
    if ! command -v "$tool" >/dev/null 2>&1; then
      fail "tools: '$tool' in available_tools but not found by command -v"
      tool_check_fail=1
    fi
  done <<< "$tools_list"
  if [ "$tool_check_fail" -eq 0 ]; then
    pass "tools: all reported tools pass command -v"
  fi
else
  pass "tools: empty available_tools is valid (no spine tools installed)"
fi

# Cross-check: a tool we know is NOT installed must NOT appear in available_tools
FAKE_TOOL="definitely-not-a-real-tool-xyz123"
assert_not_contains "tools: fake tool absent" "$TOOLS_JSON" ".available_tools" "$FAKE_TOOL"

# ---------------------------------------------------------------------------
# Fixture 9: Empty repo → all flags false, ecosystems empty
# ---------------------------------------------------------------------------
echo ""
echo "=== Fixture: empty repo ==="
FIX_EMPTY=$(make_fixture "empty-repo")
EMPTY_JSON=$(run_detector "$FIX_EMPTY")
assert_empty_array  "empty: no ecosystems"      "$EMPTY_JSON" ".detected_ecosystems"
assert_empty_array  "empty: no frameworks"      "$EMPTY_JSON" ".project_shape.frameworks"
assert_empty_array  "empty: no packages"        "$EMPTY_JSON" ".project_shape.monorepo_packages"
assert_bool         "empty: no migrations"      "$EMPTY_JSON" ".project_shape.has_migrations" "false"
assert_bool         "empty: no dockerfile"      "$EMPTY_JSON" ".project_shape.has_dockerfile" "false"
assert_bool         "empty: no workflows"       "$EMPTY_JSON" ".project_shape.has_workflows"  "false"
assert_bool         "empty: not extension"      "$EMPTY_JSON" ".project_shape.is_extension"   "false"
assert_bool         "empty: not mobile"         "$EMPTY_JSON" ".project_shape.is_mobile"      "false"

# ---------------------------------------------------------------------------
# Fixture 10: Mobile repo (ios/ directory)
# ---------------------------------------------------------------------------
echo ""
echo "=== Fixture: Mobile repo (ios dir) ==="
FIX_MOB=$(make_fixture "mobile-repo")
mkdir -p "$FIX_MOB/ios"
touch "$FIX_MOB/ios/Info.plist"

MOB_JSON=$(run_detector "$FIX_MOB")
assert_bool         "mobile: is_mobile true"    "$MOB_JSON" ".project_shape.is_mobile" "true"

# ---------------------------------------------------------------------------
# Fixture 11: Polyglot repo (go.mod + package.json) → both ecosystems detected
# ---------------------------------------------------------------------------
echo ""
echo "=== Fixture: Polyglot repo (Go + JavaScript) ==="
FIX_POLY=$(make_fixture "polyglot-repo")
cat > "$FIX_POLY/go.mod" <<'GOMOD'
module github.com/example/polyapp

go 1.21
GOMOD
cat > "$FIX_POLY/package.json" <<'JSON'
{
  "name": "polyapp-frontend",
  "version": "1.0.0"
}
JSON

POLY_JSON=$(run_detector "$FIX_POLY")
assert_contains     "poly: detected go"          "$POLY_JSON" ".detected_ecosystems" "go"
assert_contains     "poly: detected javascript"  "$POLY_JSON" ".detected_ecosystems" "javascript"

# ---------------------------------------------------------------------------
# Fixture 12: has_migrations false-positive guard
#   - repo has fixtures/seed.sql (.sql file) but NO migration directory
#   - has_migrations must be false; sql ecosystem must still be detected
# ---------------------------------------------------------------------------
echo ""
echo "=== Fixture: seed.sql only (no migration dir) ==="
FIX_SEED=$(make_fixture "seed-only-repo")
mkdir -p "$FIX_SEED/fixtures"
cat > "$FIX_SEED/fixtures/seed.sql" <<'SQL'
INSERT INTO users (email) VALUES ('test@example.com');
SQL

SEED_JSON=$(run_detector "$FIX_SEED")
assert_bool         "seed: has_migrations false" "$SEED_JSON" ".project_shape.has_migrations" "false"
assert_contains     "seed: sql ecosystem present" "$SEED_JSON" ".detected_ecosystems" "sql"

# ---------------------------------------------------------------------------
# Fixture 13: has_iac via Dockerfile
# ---------------------------------------------------------------------------
echo ""
echo "=== Fixture: has_iac via Dockerfile ==="
FIX_IAC_DOCKER=$(make_fixture "iac-docker-repo")
cat > "$FIX_IAC_DOCKER/Dockerfile" <<'EOF'
FROM ubuntu:22.04
RUN apt-get update
EOF

IAC_DOCKER_JSON=$(run_detector "$FIX_IAC_DOCKER")
assert_bool "iac-docker: has_iac true"      "$IAC_DOCKER_JSON" ".project_shape.has_iac" "true"
assert_bool "iac-docker: has_dockerfile true" "$IAC_DOCKER_JSON" ".project_shape.has_dockerfile" "true"

# ---------------------------------------------------------------------------
# Fixture 14: has_iac via Terraform (.tf file)
# ---------------------------------------------------------------------------
echo ""
echo "=== Fixture: has_iac via Terraform (.tf file) ==="
FIX_IAC_TF=$(make_fixture "iac-tf-repo")
cat > "$FIX_IAC_TF/main.tf" <<'EOF'
resource "aws_s3_bucket" "example" {
  bucket = "my-tf-test-bucket"
}
EOF

IAC_TF_JSON=$(run_detector "$FIX_IAC_TF")
assert_bool         "iac-tf: has_iac true"        "$IAC_TF_JSON" ".project_shape.has_iac" "true"
assert_bool         "iac-tf: no dockerfile"       "$IAC_TF_JSON" ".project_shape.has_dockerfile" "false"
assert_contains     "iac-tf: terraform ecosystem" "$IAC_TF_JSON" ".detected_ecosystems" "terraform"

# ---------------------------------------------------------------------------
# Fixture 15: has_iac false for a plain JS repo (no IaC signals)
# ---------------------------------------------------------------------------
echo ""
echo "=== Fixture: has_iac false for plain JS repo ==="
FIX_IAC_NONE=$(make_fixture "no-iac-repo")
cat > "$FIX_IAC_NONE/package.json" <<'JSON'
{"name":"no-iac","version":"1.0.0"}
JSON

IAC_NONE_JSON=$(run_detector "$FIX_IAC_NONE")
assert_bool "no-iac: has_iac false" "$IAC_NONE_JSON" ".project_shape.has_iac" "false"

# ---------------------------------------------------------------------------
# Fixture 16: has_iac via k8s manifest directory
# ---------------------------------------------------------------------------
echo ""
echo "=== Fixture: has_iac via k8s manifest directory ==="
FIX_IAC_K8S=$(make_fixture "iac-k8s-repo")
mkdir -p "$FIX_IAC_K8S/k8s"
cat > "$FIX_IAC_K8S/k8s/deployment.yaml" <<'EOF'
apiVersion: apps/v1
kind: Deployment
metadata:
  name: my-app
spec:
  replicas: 1
EOF

IAC_K8S_JSON=$(run_detector "$FIX_IAC_K8S")
assert_bool "iac-k8s: has_iac true" "$IAC_K8S_JSON" ".project_shape.has_iac" "true"

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
echo ""
echo "=================================="
echo "Results: $PASS_COUNT passed, $FAIL_COUNT failed"
echo "=================================="

if [ ${#FAILURES[@]} -gt 0 ]; then
  echo ""
  echo "Failed tests:"
  for f in "${FAILURES[@]}"; do
    echo "  - $f"
  done
  exit 1
fi

exit 0
