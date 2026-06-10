#!/usr/bin/env bash
# CCGM audit spine -- test suite
#
# Tests:
#   1. All tools forced-absent -> graceful skip + notes + coverage-gap entries, exit 0
#   2. Injection fixture: a file named "evil; touch PWNED" -> no PWNED file after run
#   3. Config-isolation fixture: eslint wrapper does NOT load repo .eslintrc.js
#   4. (When gitleaks IS installed) >= 1 normalized finding validates against finding.schema.json
#   5. shellcheck clean for all wrappers
#
# Exit code: 0 = all tests passed, 1 = failure

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SPINE_DIR="$SCRIPT_DIR/../scripts/spine"
FIXTURES_DIR="$SCRIPT_DIR/fixtures"
SCHEMA_FILE="$SCRIPT_DIR/../schemas/finding.schema.json"

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

# Validate a single JSON object against finding.schema.json using Python stdlib.
# Returns:
#   0  valid finding
#   1  not a finding (type field = skipped/coverage_gap/provenance -- skip silently)
#   2  invalid finding (schema violation)
validate_finding() {
  local json_line="$1"
  python3 - "$json_line" << 'PYEOF'
import json
import re
import sys

line = sys.argv[1]

try:
    obj = json.loads(line)
except json.JSONDecodeError:
    sys.exit(1)

if not isinstance(obj, dict):
    sys.exit(1)

# Skip non-finding records
if obj.get("type") in ("skipped", "coverage_gap", "provenance"):
    sys.exit(1)

# Check required fields
required = {"check_id", "rule_id", "severity", "confidence", "location", "message", "fingerprint", "detection", "source"}
missing = required - obj.keys()
if missing:
    print("Missing: " + str(sorted(missing)), file=sys.stderr)
    sys.exit(2)

# check_id pattern
if not re.fullmatch(r"[a-z0-9_-]+/[a-z0-9_.-]+", obj["check_id"]):
    print("Bad check_id: " + obj["check_id"], file=sys.stderr)
    sys.exit(2)

# severity
if obj["severity"] not in ("critical", "high", "medium", "low", "info"):
    print("Bad severity: " + obj["severity"], file=sys.stderr)
    sys.exit(2)

# confidence
if obj["confidence"] not in ("high", "medium", "low"):
    print("Bad confidence: " + obj["confidence"], file=sys.stderr)
    sys.exit(2)

# detection
if obj["detection"] not in ("tool", "llm", "hybrid"):
    print("Bad detection: " + obj["detection"], file=sys.stderr)
    sys.exit(2)

# source
if obj["source"] not in ("tool", "llm"):
    print("Bad source: " + obj["source"], file=sys.stderr)
    sys.exit(2)

# location
loc = obj.get("location", {})
if not isinstance(loc, dict) or "path" not in loc or "line" not in loc:
    print("Bad location", file=sys.stderr)
    sys.exit(2)
if not isinstance(loc["line"], int) or loc["line"] < 1:
    print("Bad line number", file=sys.stderr)
    sys.exit(2)

# fingerprint pattern
fp = obj.get("fingerprint", "")
if not re.fullmatch(r"[A-Za-z0-9_.:+/=\-]{8,128}", fp):
    print("Bad fingerprint: " + fp, file=sys.stderr)
    sys.exit(2)

sys.exit(0)
PYEOF
}

# ---------------------------------------------------------------------------
# Temp dir for the whole test run
# ---------------------------------------------------------------------------
TESTRUN_TMPDIR="$(mktemp -d /tmp/ccgm-test-XXXXXX)"
trap 'rm -rf "$TESTRUN_TMPDIR"' EXIT

# Create a minimal repo for tests that need one
TMPDIR_REPO="$TESTRUN_TMPDIR/repo"
mkdir -p "$TMPDIR_REPO"
printf '{"name":"test","version":"1.0.0"}\n' > "$TMPDIR_REPO/package.json"
printf 'hello world\n' > "$TMPDIR_REPO/hello.txt"

# ---------------------------------------------------------------------------
# Test 1: All tools forced-absent -> graceful skip + coverage-gap, exit 0
#
# Strategy: create a stubs directory with stub scripts for each tool that
# just exit 1 (simulating "tool not found" in the PATH check inside each
# wrapper). The wrappers use "command -v <tool>" to detect presence, so
# placing a script named after each tool in a prefix directory on PATH
# makes "command -v" succeed but the actual call fail.
#
# Better approach: wrappers call "command -v gitleaks" etc. If gitleaks is
# NOT on PATH, they emit skip and exit 0. So we need a PATH where gitleaks
# etc. are genuinely absent. We build this from known system-only dirs +
# python3/bash/find locations.
# ---------------------------------------------------------------------------
printf '\nTest 1: All tools forced-absent -> graceful skip\n'

# Build a PATH containing only essential non-audit binaries
SYSTEM_BINS=""
for bin in python3 bash find date mktemp cp rm mv printf head grep; do
  BINPATH="$(command -v "$bin" 2>/dev/null || true)"
  if [[ -n "$BINPATH" ]]; then
    BINDIR="$(dirname "$BINPATH")"
    case ":$SYSTEM_BINS:" in
      *":$BINDIR:"*) ;;  # already present
      *) SYSTEM_BINS="${SYSTEM_BINS:+$SYSTEM_BINS:}$BINDIR" ;;
    esac
  fi
done
# Always include standard system paths
RESTRICTED_PATH="$SYSTEM_BINS:/usr/bin:/bin"

SPINE_OUTPUT="$TESTRUN_TMPDIR/test1-output.jsonl"

set +e
PATH="$RESTRICTED_PATH" bash "$SPINE_DIR/run.sh" \
  --repo "$TMPDIR_REPO" \
  --output "$SPINE_OUTPUT" \
  2>/dev/null
T1_EXIT=$?
set -e

if [[ $T1_EXIT -eq 0 ]]; then
  pass "run.sh exits 0 when tools absent"
else
  fail "run.sh exits $T1_EXIT (expected 0) when tools absent"
fi

if [[ -s "$SPINE_OUTPUT" ]]; then
  pass "run.sh produced output (provenance + skip notes)"
else
  fail "run.sh produced no output (expected at least provenance record)"
fi

# Check for skipped notes
SKIP_COUNT="$(grep -c '"type":"skipped"' "$SPINE_OUTPUT" 2>/dev/null || printf '0')"
if [[ "$SKIP_COUNT" -gt 0 ]]; then
  pass "found $SKIP_COUNT skipped note(s) for absent tools"
else
  fail "no skipped notes found for absent tools (expected >= 1)"
fi

# Check for coverage-gap entries
GAP_COUNT="$(grep -c '"type":"coverage_gap"' "$SPINE_OUTPUT" 2>/dev/null || printf '0')"
if [[ "$GAP_COUNT" -gt 0 ]]; then
  pass "found $GAP_COUNT coverage-gap entries for absent tools"
else
  fail "no coverage_gap entries found for absent tools (expected >= 1)"
fi

# All lines should be valid JSON
INVALID_JSON=0
while IFS= read -r line; do
  if [[ -z "$line" ]]; then continue; fi
  if ! python3 -c "import json,sys; json.loads(sys.argv[1])" "$line" 2>/dev/null; then
    INVALID_JSON=$((INVALID_JSON + 1))
  fi
done < "$SPINE_OUTPUT"

if [[ $INVALID_JSON -eq 0 ]]; then
  pass "all output lines are valid JSON"
else
  fail "$INVALID_JSON output line(s) are invalid JSON"
fi

# ---------------------------------------------------------------------------
# Test 1b: Adversarial repo path (contains " and space) -> provenance is
# valid JSON.  Verifies the json.dumps provenance fix (not printf).
# ---------------------------------------------------------------------------
printf '\nTest 1b: Adversarial repo path -> provenance line is valid JSON\n'

WEIRD_DIR="$TESTRUN_TMPDIR/repo-with-quote\"-and space"
mkdir -p "$WEIRD_DIR"
printf '{"name":"weird"}\n' > "$WEIRD_DIR/package.json"

WEIRD_OUTPUT="$TESTRUN_TMPDIR/test1b-output.jsonl"
set +e
bash "$SPINE_DIR/run.sh" \
  --repo "$WEIRD_DIR" \
  --tools "gitleaks" \
  --output "$WEIRD_OUTPUT" \
  2>/dev/null
WEIRD_EXIT=$?
set -e

if [[ $WEIRD_EXIT -eq 0 ]]; then
  pass "spine exits 0 on adversarial repo path"
else
  fail "spine exits $WEIRD_EXIT on adversarial repo path (expected 0)"
fi

# Extract and validate the provenance line using python3 (grep patterns vary by
# platform; json.dumps adds spaces after ":" so a no-space grep would miss it).
PROV_VALID="$(python3 - "$WEIRD_OUTPUT" << 'PYEOF'
import json, sys
with open(sys.argv[1]) as f:
    for raw in f:
        raw = raw.strip()
        if not raw:
            continue
        try:
            obj = json.loads(raw)
        except json.JSONDecodeError:
            print("invalid")
            sys.exit(0)
        if obj.get("type") == "provenance":
            # round-trip succeeded -- JSON is valid
            print("valid")
            sys.exit(0)
print("missing")
PYEOF
)"
if [[ "$PROV_VALID" == "valid" ]]; then
  pass "provenance line is valid JSON for adversarial repo path (contains quote + space)"
elif [[ "$PROV_VALID" == "missing" ]]; then
  fail "no provenance line found in output for adversarial repo path"
else
  fail "provenance line is NOT valid JSON for adversarial repo path -- printf escaping bug?"
fi

# ---------------------------------------------------------------------------
# Test 2: Injection fixture -- no PWNED file after spine run
# ---------------------------------------------------------------------------
printf '\nTest 2: Injection fixture -- no PWNED file created\n'

INJECTION_DIR="$FIXTURES_DIR/injection"

# Ensure no PWNED file exists before the test
rm -f "$INJECTION_DIR/PWNED"
rm -f "$(pwd)/PWNED"
rm -f "/tmp/PWNED"

pass "precondition: cleaned any stale PWNED file"

INJECTION_OUTPUT="$TESTRUN_TMPDIR/test2-output.jsonl"

set +e
bash "$SPINE_DIR/run.sh" \
  --repo "$INJECTION_DIR" \
  --output "$INJECTION_OUTPUT" \
  2>/dev/null
INJECT_EXIT=$?
set -e

if [[ $INJECT_EXIT -eq 0 ]]; then
  pass "spine exits 0 on injection fixture"
else
  fail "spine exits $INJECT_EXIT on injection fixture (expected 0)"
fi

# The critical check: no PWNED file should exist anywhere
PWNED_FOUND=0
for PWNED_PATH in "$INJECTION_DIR/PWNED" "$(pwd)/PWNED" "/tmp/PWNED"; do
  if [[ -f "$PWNED_PATH" ]]; then
    PWNED_FOUND=$((PWNED_FOUND + 1))
    echo "  PWNED found at: $PWNED_PATH" >&2
  fi
done

if [[ $PWNED_FOUND -eq 0 ]]; then
  pass "no PWNED file created -- shell injection is inert"
else
  fail "PWNED file was created -- shell injection succeeded (CRITICAL FAILURE)"
fi

# ---------------------------------------------------------------------------
# Test 3: Config-isolation -- eslint does NOT load repo .eslintrc.js
# ---------------------------------------------------------------------------
printf '\nTest 3: Config-isolation -- eslint does not load repo config\n'

CONFIG_ISO_DIR="$FIXTURES_DIR/config-isolation"

# The config-isolation fixture has .eslintrc.js that throws an error if loaded.
# With --no-config-lookup, eslint ignores this file and uses only our --rule flags.
# Without --no-config-lookup, eslint would load .eslintrc.js and crash (exit 2).
# The test: wrapper exits 0, output is valid JSON.

ISO_OUTPUT="$TESTRUN_TMPDIR/test3-output.jsonl"

if command -v eslint > /dev/null 2>&1; then
  set +e
  bash "$SPINE_DIR/wrap-eslint.sh" "$CONFIG_ISO_DIR" > "$ISO_OUTPUT" 2>/dev/null
  ESLINT_WRAP_EXIT=$?
  set -e

  if [[ $ESLINT_WRAP_EXIT -eq 0 ]]; then
    pass "eslint wrapper exits 0 with config-isolation fixture (--no-config-lookup worked)"
  else
    fail "eslint wrapper exits $ESLINT_WRAP_EXIT -- config isolation may have failed (loaded .eslintrc.js?)"
  fi

  if [[ -s "$ISO_OUTPUT" ]]; then
    ISO_FIRST_LINE="$(head -1 "$ISO_OUTPUT")"
    if python3 -c "import json,sys; json.loads(sys.argv[1])" "$ISO_FIRST_LINE" 2>/dev/null; then
      pass "config-isolation output is valid JSON (not a crash dump)"
    else
      fail "config-isolation output first line is not valid JSON"
    fi
  else
    pass "eslint wrapper produced no output (no matches in fixture -- acceptable)"
  fi
else
  pass "eslint not installed -- config-isolation test skipped"
fi

# ---------------------------------------------------------------------------
# Test 4: gitleaks (if installed) produces >= 1 valid finding
# ---------------------------------------------------------------------------
printf '\nTest 4: gitleaks (if installed) produces valid finding(s)\n'

if command -v gitleaks > /dev/null 2>&1; then
  # The injection fixture has a proper fake GitHub PAT in safe.txt
  GL_OUTPUT="$TESTRUN_TMPDIR/test4-gl.jsonl"

  set +e
  bash "$SPINE_DIR/wrap-gitleaks.sh" "$INJECTION_DIR" > "$GL_OUTPUT" 2>/dev/null
  GL_EXIT=$?
  set -e

  if [[ $GL_EXIT -eq 0 ]]; then
    pass "gitleaks wrapper exits 0"
  else
    fail "gitleaks wrapper exits $GL_EXIT (expected 0)"
  fi

  # Count valid findings (not skipped/coverage_gap/provenance)
  VALID_FINDINGS=0
  INVALID_FINDINGS=0

  while IFS= read -r line; do
    if [[ -z "$line" ]]; then continue; fi

    # Check if this is a non-finding record
    IS_NOTE="$(python3 -c "
import json,sys
try:
    obj = json.loads(sys.argv[1])
    if isinstance(obj, dict) and obj.get('type') in ('skipped','coverage_gap','provenance'):
        print('yes')
    else:
        print('no')
except Exception:
    print('yes')
" "$line" 2>/dev/null || printf 'yes')"

    if [[ "$IS_NOTE" == "yes" ]]; then
      continue
    fi

    VALIDATE_EXIT=0
    validate_finding "$line" || VALIDATE_EXIT=$?
    if [[ $VALIDATE_EXIT -eq 0 ]]; then
      VALID_FINDINGS=$((VALID_FINDINGS + 1))
    elif [[ $VALIDATE_EXIT -eq 2 ]]; then
      INVALID_FINDINGS=$((INVALID_FINDINGS + 1))
    fi
  done < "$GL_OUTPUT"

  if [[ $VALID_FINDINGS -ge 1 ]]; then
    pass "gitleaks produced $VALID_FINDINGS valid finding(s) conforming to finding.schema.json"
  else
    # Emit what gitleaks produced for debugging
    printf '  (gitleaks output was: %s lines)\n' "$(wc -l < "$GL_OUTPUT" | tr -d ' ')"
    head -3 "$GL_OUTPUT" | while IFS= read -r l; do printf '    %s\n' "$l"; done
    fail "gitleaks produced 0 valid findings (expected >= 1; check safe.txt fake token)"
  fi

  if [[ $INVALID_FINDINGS -gt 0 ]]; then
    fail "gitleaks produced $INVALID_FINDINGS finding(s) that do NOT conform to finding.schema.json"
  else
    pass "all gitleaks findings conform to finding.schema.json"
  fi
else
  pass "gitleaks not installed -- live-tool test skipped"
fi

# ---------------------------------------------------------------------------
# Test 5: shellcheck -- all wrappers must be clean
# ---------------------------------------------------------------------------
printf '\nTest 5: shellcheck on all shell wrappers\n'

if command -v shellcheck > /dev/null 2>&1; then
  SHELL_SCRIPTS=(
    "$SPINE_DIR/run.sh"
    "$SPINE_DIR/wrap-gitleaks.sh"
    "$SPINE_DIR/wrap-semgrep.sh"
    "$SPINE_DIR/wrap-dep-audit.sh"
    "$SPINE_DIR/wrap-knip.sh"
    "$SPINE_DIR/wrap-eslint.sh"
    "$SPINE_DIR/wrap-govulncheck.sh"
    "$SPINE_DIR/wrap-bandit.sh"
    "$SPINE_DIR/wrap-hadolint.sh"
    "$SPINE_DIR/wrap-actionlint.sh"
    "$SPINE_DIR/wrap-trivy.sh"
    "$SPINE_DIR/wrap-zizmor.sh"
    "$SPINE_DIR/wrap-pinact.sh"
    "$SPINE_DIR/wrap-squawk.sh"
    "$SPINE_DIR/wrap-sqlfluff.sh"
    "$SPINE_DIR/wrap-checkov.sh"
    "$SPINE_DIR/wrap-pip-audit.sh"
    "$SPINE_DIR/wrap-cargo-audit.sh"
    "$SPINE_DIR/wrap-bundler-audit.sh"
  )

  for script in "${SHELL_SCRIPTS[@]}"; do
    if [[ ! -f "$script" ]]; then
      fail "shellcheck: script not found: $script"
      continue
    fi
    SC_OUTPUT="$(shellcheck -S warning "$script" 2>&1 || true)"
    if [[ -z "$SC_OUTPUT" ]]; then
      pass "shellcheck clean: $(basename "$script")"
    else
      fail "shellcheck issues in $(basename "$script"):"
      printf '%s\n' "$SC_OUTPUT" | head -10
    fi
  done
else
  fail "shellcheck not installed -- cannot verify shell safety"
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
