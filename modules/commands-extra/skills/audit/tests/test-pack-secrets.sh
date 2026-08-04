#!/usr/bin/env bash
# CCGM audit -- test-pack-secrets.sh
# Tests for Epic 2.6: Secrets pack + gitleaks full-history scan.
#
# What this tests:
#   1. pack.json + checks.md validate (lint-pack passes on secrets pack)
#   2. severity-rubric.json is valid JSON and contains all secrets/* ids
#   3. (REAL-TOOL E2E) gitleaks full-history scan via wrap-gitleaks.sh with
#      CCGM_GITLEAKS_HISTORY=1:
#        a. Creates a throwaway git repo (mktemp, core.hooksPath=/dev/null)
#        b. Commits a fake credential in a prior commit (ADV-009 fragment-assembled)
#        c. Removes the file at HEAD
#        d. Also commits a .env file with a fake-looking assignment
#        e. Runs the real gitleaks history scan via the wrapper
#        f. Asserts >= 1 secrets/leaked-credential finding from history
#        g. Asserts the matched value is REDACTED in output (assembled key absent)
#        h. Asserts the .env file is tracked in git (grep check)
#   4. Working-tree mode (default, no CCGM_GITLEAKS_HISTORY) still works after
#      the wrapper edit (regression guard for test-merge.sh's e2e).
#
# ADV-009: the fake-secret fixture is CONSTRUCTED AT RUNTIME from fragments;
# the assembled string never appears in this tracked file.
#
# Usage: bash modules/commands-extra/skills/audit/tests/test-pack-secrets.sh
# Exit:  0 = all tests passed, non-zero = at least one failure

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
AUDIT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
WRAP_GL="$AUDIT_DIR/scripts/spine/wrap-gitleaks.sh"
LINT_PACK="$AUDIT_DIR/scripts/lint-pack.py"
LINT_RUBRIC="$AUDIT_DIR/scripts/lint-rubric.py"
RUBRIC_FILE="$AUDIT_DIR/schemas/severity-rubric.json"
PACK_DIR="$AUDIT_DIR/packs/secrets"

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

TESTRUN_DIR="$(mktemp -d /tmp/ccgm-test-pack-secrets-XXXXXX)"
CLEANUP_DIRS=("$TESTRUN_DIR")
trap 'rm -rf "${CLEANUP_DIRS[@]}"' EXIT

# ---------------------------------------------------------------------------
# Test 1: lint-pack passes on the secrets pack
# ---------------------------------------------------------------------------
printf '\nTest 1: lint-pack passes on secrets pack\n'

set +e
LINT_OUT="$(python3 "$LINT_PACK" --packs-dir "$PACK_DIR/.." --rubric "$RUBRIC_FILE" 2>&1)"
LINT_EXIT=$?
set -e

# Grep for the secrets pack specifically
# Herestring, not a pipe: `producer | grep -q` can SIGPIPE-kill the
# producer if grep exits on its first match before the producer finishes
# writing, turning a genuine match into a reported failure (see #943,
# #945). A herestring has no second process to race against.
if grep -q "PASS: secrets" <<< "$LINT_OUT"; then
  pass "t1: lint-pack PASS for secrets pack"
elif grep -q "FAIL: secrets" <<< "$LINT_OUT"; then
  fail "t1: lint-pack FAIL for secrets pack"
  printf '    Output: %s\n' "$LINT_OUT" >&2
else
  # Fall back to overall exit code
  if [[ $LINT_EXIT -eq 0 ]]; then
    pass "t1: lint-pack exits 0 (all packs pass)"
  else
    fail "t1: lint-pack exits $LINT_EXIT"
    printf '    Output: %s\n' "$LINT_OUT" >&2
  fi
fi

# ---------------------------------------------------------------------------
# Test 2: lint-pack passes when run against secrets pack directory alone
# ---------------------------------------------------------------------------
printf '\nTest 2: lint-pack passes against secrets pack directory directly\n'

set +e
LINT2_OUT="$(python3 "$LINT_PACK" --packs-dir "$PACK_DIR" --rubric "$RUBRIC_FILE" 2>&1)"
LINT2_EXIT=$?
set -e

if [[ $LINT2_EXIT -eq 0 ]]; then
  pass "t2: lint-pack exits 0 on secrets pack dir"
else
  fail "t2: lint-pack exits $LINT2_EXIT on secrets pack dir"
  printf '    Output: %s\n' "$LINT2_OUT" >&2
fi

# ---------------------------------------------------------------------------
# Test 3: rubric valid JSON + contains secrets/* ids
# ---------------------------------------------------------------------------
printf '\nTest 3: rubric valid JSON + contains secrets/* check ids\n'

if python3 -c "import json, sys; json.load(open('$RUBRIC_FILE'))" 2>/dev/null; then
  pass "t3: rubric parses as valid JSON"
else
  fail "t3: rubric is not valid JSON"
fi

RUBRIC_IDS="$(python3 - "$RUBRIC_FILE" << 'PYEOF'
import json, sys
with open(sys.argv[1]) as fh:
    rubric = json.load(fh)
checks = rubric.get("checks", {})
for cid in ["secrets/leaked-credential", "secrets/tracked-env-file",
            "secrets/tracked-key-material", "secrets/history-only-credential"]:
    if cid in checks:
        print("FOUND:" + cid)
    else:
        print("MISSING:" + cid)
PYEOF
)"

for line in $RUBRIC_IDS; do
  if [[ "$line" == FOUND:* ]]; then
    pass "t3: rubric has entry for ${line#FOUND:}"
  else
    fail "t3: rubric missing entry for ${line#MISSING:}"
  fi
done

# ---------------------------------------------------------------------------
# Test 4: lint-rubric passes on the real rubric file
# ---------------------------------------------------------------------------
printf '\nTest 4: lint-rubric passes on real rubric file\n'

set +e
LRUBRIC_OUT="$(python3 "$LINT_RUBRIC" --rubric "$RUBRIC_FILE" 2>&1)"
LRUBRIC_EXIT=$?
set -e

if [[ $LRUBRIC_EXIT -eq 0 ]]; then
  pass "t4: lint-rubric exits 0 on real severity-rubric.json"
else
  fail "t4: lint-rubric exits $LRUBRIC_EXIT on real severity-rubric.json"
  printf '    Output: %s\n' "$LRUBRIC_OUT" >&2
fi

# ---------------------------------------------------------------------------
# Test 5 (REAL-TOOL E2E): gitleaks full-history scan via wrap-gitleaks.sh
# ---------------------------------------------------------------------------
printf '\nTest 5 (real-tool e2e): gitleaks full-history scan (CCGM_GITLEAKS_HISTORY=1)\n'

if ! command -v gitleaks > /dev/null 2>&1; then
  printf '  [SKIP] gitleaks not installed -- history e2e test skipped\n'
else
  E2E_DIR="$(mktemp -d /tmp/ccgm-secrets-e2e-XXXXXX)"
  CLEANUP_DIRS+=("$E2E_DIR")

  # Build a throwaway git repo.
  # ADV-009: the fake key is assembled at runtime from two string fragments.
  # The prefix and the suffix are NEVER concatenated in this tracked file.
  # We use a suffix that is NOT the AWS docs example ("IOSFODNN7EXAMPLE") to
  # ensure real gitleaks detection without being the allow-listed example value.
  git init "$E2E_DIR/repo" --quiet 2>/dev/null
  git -C "$E2E_DIR/repo" config user.email "test@test.test"
  git -C "$E2E_DIR/repo" config user.name "Test"
  git -C "$E2E_DIR/repo" config core.hooksPath /dev/null 2>/dev/null || true

  # Assemble the fake key at runtime from two separate variable fragments.
  # Neither variable contains a scannable key on its own.
  # The 16-char suffix uses a sequential alphabetic pattern to ensure sufficient
  # Shannon entropy for gitleaks detection (all-caps sequential triggers aws-access-token).
  # NOTE: the AWS docs example key uses "IOSFODNN7EXAMPLE" (which gitleaks allow-lists).
  # We use "ABCDEFGHIJKLMNOP" -- different, triggers real detection, not a real key.
  KEY_FRAG_A="AKIA"
  KEY_FRAG_B="ABCDEFGHIJKLMNOP"
  FAKE_KEY="${KEY_FRAG_A}${KEY_FRAG_B}"

  # Commit 1: add a file containing the fake key (simulates a secret accidentally committed)
  python3 - "$E2E_DIR/repo/leaked.env" "$FAKE_KEY" << 'PYEOF'
import sys
path, key = sys.argv[1], sys.argv[2]
with open(path, "w") as fh:
    fh.write("# Leaked credential file\n")
    fh.write("AWS_ACCESS_KEY_ID=" + key + "\n")
    fh.write("APP_ENV=production\n")
PYEOF
  git -C "$E2E_DIR/repo" add leaked.env
  git -C "$E2E_DIR/repo" commit -m "feat: initial commit with leaked credential" --quiet 2>/dev/null

  # Commit 2: remove the leaked file (history-only scenario: file absent at HEAD)
  git -C "$E2E_DIR/repo" rm leaked.env --quiet 2>/dev/null
  git -C "$E2E_DIR/repo" commit -m "fix: remove leaked credential file" --quiet 2>/dev/null

  # Commit 3: add a tracked .env file with a fake-looking assignment
  python3 - "$E2E_DIR/repo/.env" << 'PYEOF'
import sys
with open(sys.argv[1] if len(sys.argv) > 1 else ".env", "w") as fh:
    fh.write("# Application environment\n")
    fh.write("DATABASE_URL=postgres://admin:s3cr3tp4ss@db.prod.example.com/app\n")
    fh.write("APP_ENV=development\n")
PYEOF
  git -C "$E2E_DIR/repo" add .env
  git -C "$E2E_DIR/repo" commit -m "feat: add .env configuration" --quiet 2>/dev/null

  # Verify HEAD state: leaked.env must NOT exist at HEAD
  if [[ ! -f "$E2E_DIR/repo/leaked.env" ]]; then
    pass "t5: leaked.env is absent at HEAD (history-only scenario confirmed)"
  else
    fail "t5: leaked.env unexpectedly present at HEAD (test setup error)"
  fi

  # Verify .env IS tracked at HEAD
  if git -C "$E2E_DIR/repo" ls-files --error-unmatch .env 2>/dev/null; then
    pass "t5: .env is tracked in git index"
  else
    fail "t5: .env is NOT tracked in git index (test setup error)"
  fi

  # Run wrap-gitleaks.sh with CCGM_GITLEAKS_HISTORY=1 (full history scan)
  E2E_JSONL="$E2E_DIR/gitleaks-history.jsonl"
  set +e
  CCGM_GITLEAKS_HISTORY=1 bash "$WRAP_GL" "$E2E_DIR/repo" > "$E2E_JSONL" 2>/dev/null
  GL_EXIT=$?
  set -e

  if [[ $GL_EXIT -eq 0 ]]; then
    pass "t5: wrap-gitleaks exits 0 in history mode"
  else
    fail "t5: wrap-gitleaks exits $GL_EXIT in history mode (expected 0)"
  fi

  # Count secrets/leaked-credential findings from history
  HISTORY_CRED_COUNT="$(python3 - "$E2E_JSONL" << 'PYEOF'
import json, sys
count = 0
try:
    with open(sys.argv[1]) as fh:
        for l in fh:
            l = l.strip()
            if not l:
                continue
            try:
                obj = json.loads(l)
                if isinstance(obj, dict) and "type" not in obj:
                    if obj.get("check_id") == "secrets/leaked-credential":
                        count += 1
            except Exception:
                pass
except OSError:
    pass
print(count)
PYEOF
)"

  if [[ "$HISTORY_CRED_COUNT" -ge 1 ]]; then
    pass "t5: >= 1 secrets/leaked-credential finding from full history scan (got $HISTORY_CRED_COUNT)"
  else
    fail "t5: 0 secrets/leaked-credential findings from history scan (expected >= 1)"
  fi

  # Assert the assembled fake key does NOT appear in the JSONL output (redaction held)
  if grep -qF "$FAKE_KEY" "$E2E_JSONL" 2>/dev/null; then
    fail "t5: assembled fake key appears in gitleaks JSONL output -- redaction failed"
  else
    pass "t5: assembled fake key is NOT in gitleaks JSONL output -- redaction held"
  fi

  # Assert redaction format is present (first-4+length pattern)
  # The fake key starts with KEY_FRAG_A (4 chars) and gitleaks redacts to first4[redacted:len=N]
  REDACTION_PRESENT="$(python3 - "$E2E_JSONL" "$KEY_FRAG_A" << 'PYEOF'
import json, sys, re
found = False
prefix = sys.argv[2]
try:
    with open(sys.argv[1]) as fh:
        for l in fh:
            l = l.strip()
            if not l:
                continue
            try:
                obj = json.loads(l)
                if isinstance(obj, dict) and "type" not in obj:
                    msg = obj.get("message", "")
                    # Check for first-4+[redacted:len=N] pattern in the message
                    pattern = re.compile(re.escape(prefix) + r'\[redacted:len=\d+\]')
                    if pattern.search(msg):
                        found = True
                        break
            except Exception:
                pass
except OSError:
    pass
print("yes" if found else "no")
PYEOF
)"

  if [[ "$REDACTION_PRESENT" == "yes" ]]; then
    pass "t5: redaction format (first4[redacted:len=N]) present in finding message"
  else
    fail "t5: redaction format not found in finding message (expected first4[redacted:len=N])"
  fi

  # Check the properties.tool field is set to gitleaks
  TOOL_PROP="$(python3 - "$E2E_JSONL" << 'PYEOF'
import json, sys
try:
    with open(sys.argv[1]) as fh:
        for l in fh:
            l = l.strip()
            if not l:
                continue
            try:
                obj = json.loads(l)
                if isinstance(obj, dict) and "type" not in obj:
                    if obj.get("check_id") == "secrets/leaked-credential":
                        props = obj.get("properties", {})
                        print(props.get("tool", "missing"))
                        sys.exit(0)
            except Exception:
                pass
except OSError:
    pass
print("not_found")
PYEOF
)"

  if [[ "$TOOL_PROP" == "gitleaks" ]]; then
    pass "t5: properties.tool=gitleaks on secrets/leaked-credential finding"
  else
    fail "t5: properties.tool='$TOOL_PROP' (expected 'gitleaks')"
  fi

  # Test 6: verify .env file is tracked in git (grep check for tracked-env-file)
  printf '\nTest 6: .env file tracked in git (grep-based tracked-env-file check)\n'

  ENV_TRACKED="$(git -C "$E2E_DIR/repo" ls-files .env 2>/dev/null)"
  if [[ "$ENV_TRACKED" == ".env" ]]; then
    pass "t6: .env is listed in git ls-files (would be flagged by secrets/tracked-env-file)"
  else
    fail "t6: .env is NOT listed in git ls-files (expected to be tracked)"
  fi

  # Verify .env contains a real-looking assignment (non-placeholder value)
  ENV_HAS_REAL_ASSIGNMENT="$(python3 - "$E2E_DIR/repo/.env" << 'PYEOF'
import re, sys
try:
    with open(sys.argv[1]) as fh:
        content = fh.read()
    # Look for KEY=value where value is not a placeholder (len >= 8, not placeholder words)
    PLACEHOLDER_WORDS = {"your", "replace", "example", "todo", "placeholder", "changeme"}
    for line in content.splitlines():
        m = re.match(r'^[A-Z_][A-Z0-9_]+=(.+)$', line.strip())
        if m:
            val = m.group(1).strip('"\'')
            if len(val) >= 8:
                lower_val = val.lower()
                if not any(p in lower_val for p in PLACEHOLDER_WORDS):
                    print("yes")
                    sys.exit(0)
    print("no")
except OSError:
    print("error")
PYEOF
)"

  if [[ "$ENV_HAS_REAL_ASSIGNMENT" == "yes" ]]; then
    pass "t6: .env contains real-looking assignment (non-placeholder value >= 8 chars)"
  else
    fail "t6: .env does not contain real-looking assignment (test data issue)"
  fi

  # Test 7: working-tree mode (default, no CCGM_GITLEAKS_HISTORY) regression guard
  # Ensures the wrapper edit did not break the working-tree path.
  printf '\nTest 7: working-tree mode regression guard (no CCGM_GITLEAKS_HISTORY)\n'

  WT_E2E_DIR="$(mktemp -d /tmp/ccgm-secrets-wt-XXXXXX)"
  CLEANUP_DIRS+=("$WT_E2E_DIR")

  git init "$WT_E2E_DIR/repo" --quiet 2>/dev/null
  git -C "$WT_E2E_DIR/repo" config user.email "test@test.test"
  git -C "$WT_E2E_DIR/repo" config user.name "Test"
  git -C "$WT_E2E_DIR/repo" config core.hooksPath /dev/null 2>/dev/null || true

  # Write a file containing the assembled fake key to the working tree (not committed)
  python3 - "$WT_E2E_DIR/repo/wt_secrets.env" "$FAKE_KEY" << 'PYEOF'
import sys
path, key = sys.argv[1], sys.argv[2]
with open(path, "w") as fh:
    fh.write("# Working tree credential test\n")
    fh.write("AWS_ACCESS_KEY_ID=" + key + "\n")
PYEOF

  WT_JSONL="$WT_E2E_DIR/gitleaks-wt.jsonl"
  set +e
  bash "$WRAP_GL" "$WT_E2E_DIR/repo" > "$WT_JSONL" 2>/dev/null
  WT_EXIT=$?
  set -e

  if [[ $WT_EXIT -eq 0 ]]; then
    pass "t7: wrap-gitleaks exits 0 in working-tree mode (default)"
  else
    fail "t7: wrap-gitleaks exits $WT_EXIT in working-tree mode (expected 0)"
  fi

  WT_CRED_COUNT="$(python3 - "$WT_JSONL" << 'PYEOF'
import json, sys
count = 0
try:
    with open(sys.argv[1]) as fh:
        for l in fh:
            l = l.strip()
            if not l:
                continue
            try:
                obj = json.loads(l)
                if isinstance(obj, dict) and "type" not in obj:
                    if obj.get("check_id") == "secrets/leaked-credential":
                        count += 1
            except Exception:
                pass
except OSError:
    pass
print(count)
PYEOF
)"

  if [[ "$WT_CRED_COUNT" -ge 1 ]]; then
    pass "t7: working-tree mode finds >= 1 secrets/leaked-credential in working tree (got $WT_CRED_COUNT)"
  else
    fail "t7: working-tree mode found 0 credentials in working tree (expected >= 1)"
  fi

  # Assert the assembled fake key does NOT appear in working-tree output (redaction)
  if grep -qF "$FAKE_KEY" "$WT_JSONL" 2>/dev/null; then
    fail "t7: assembled fake key appears in working-tree output -- redaction failed"
  else
    pass "t7: assembled fake key NOT in working-tree output -- redaction held"
  fi
fi

# ---------------------------------------------------------------------------
# ADV-009 self-check: this test file must not contain the assembled AKIA key
# ---------------------------------------------------------------------------
printf '\nADV-009 self-check: this file must not contain assembled AKIA key pattern\n'

SELF_GREP="$(grep -cE 'AKIA[A-Z0-9]{12,}' "$SCRIPT_DIR/test-pack-secrets.sh" 2>/dev/null || true)"
if [[ "$SELF_GREP" -eq 0 ]]; then
  pass "ADV-009: grep -nE 'AKIA[A-Z0-9]{12,}' is empty in test file"
else
  fail "ADV-009: assembled AKIA key pattern found $SELF_GREP time(s) in test file -- violates ADV-009"
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
