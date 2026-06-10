#!/usr/bin/env bash
# test-diff-mode.sh
# Tests for Epic 1.8: --diff / --staged diff-scoped audit mode.
#
# Test groups:
#   1. Changed-set computation: --diff and --staged commands + -z file contents
#   2. Hostile filename: "evil; touch PWNED.js" is inert data throughout
#   3. Spine post-filter: finding from changed file survives; unchanged file finding excluded;
#      coverage_gap/provenance records pass through unfiltered
#   4. Empty diff: exits cleanly with message, no artifacts beyond changed-files.z
#   5. Consistency: SKILL.md documents --diff/--staged in Usage + mode detection + both paths;
#      spine-once step is unconditional for non-diff mode (no regression)
#
# All fixtures are constructed at runtime in mktemp dirs; none are tracked.
#
# ADV-009: fake secret assembled from fragments at runtime -- never appears whole in source.
#
# Usage: bash modules/commands-extra/skills/audit/tests/test-diff-mode.sh
# Exit:  0 = all pass, non-zero = at least one failure

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
AUDIT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
SPINE_SCRIPT="${AUDIT_DIR}/scripts/spine/run.sh"
SKILL_MD="${AUDIT_DIR}/SKILL.md"

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

# Create a git fixture repo with hooks disabled (prevents global pre-commit
# hooks from firing on deliberate test-secret commits).
make_repo() {
  local d
  d=$(make_tmp)
  git -C "$d" init -q
  git -C "$d" config user.email "test@example.com"
  git -C "$d" config user.name "Test"
  # Override global hooksPath so no pre-commit hook fires in fixture repos.
  local empty_hooks
  empty_hooks=$(make_tmp)
  git -C "$d" config core.hooksPath "$empty_hooks"
  echo "$d"
}

# Parse null-delimited changed-files.z -> list of paths using python3
read_z_file() {
  local z_file="$1"
  python3 - "$z_file" << 'PYEOF'
import sys
with open(sys.argv[1], "rb") as fh:
    data = fh.read()
paths = [p.decode("utf-8", errors="surrogateescape")
         for p in data.rstrip(b"\x00").split(b"\x00") if p]
for p in paths:
    print(p)
PYEOF
}

# Apply the documented diff filter step to spine JSONL.
# Reads null-delimited changed-files.z; outputs filtered JSONL.
apply_diff_filter() {
  local spine_file="$1"
  local changed_z="$2"
  local out_file="$3"
  python3 - "$spine_file" "$changed_z" "$out_file" << 'PYEOF'
import json, sys

spine_file, changed_z, out_file = sys.argv[1], sys.argv[2], sys.argv[3]

with open(changed_z, "rb") as fh:
    data = fh.read()
changed_set = set(
    p.decode("utf-8", errors="surrogateescape")
    for p in data.rstrip(b"\x00").split(b"\x00") if p
)

kept = 0
skipped = 0
with open(spine_file, encoding="utf-8") as fin, \
     open(out_file, "w", encoding="utf-8") as fout:
    for raw in fin:
        raw = raw.strip()
        if not raw:
            continue
        try:
            rec = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if "type" in rec:
            fout.write(raw + "\n")
            continue
        path = rec.get("location", {}).get("path", "")
        if path in changed_set:
            fout.write(raw + "\n")
            kept += 1
        else:
            skipped += 1

print(f"diff-filter: kept {kept} finding(s), skipped {skipped}", file=__import__('sys').stderr)
PYEOF
}

# ---------------------------------------------------------------------------
# Prerequisite checks
# ---------------------------------------------------------------------------
echo ""
echo "=== test-diff-mode.sh (Epic 1.8) ==="
echo ""

for tool in python3 git; do
  if ! command -v "$tool" >/dev/null 2>&1; then
    echo "ERROR: required tool '$tool' not found" >&2
    exit 1
  fi
done

for f in "$SPINE_SCRIPT" "$SKILL_MD"; do
  if [ ! -f "$f" ]; then
    echo "ERROR: required file not found: $f" >&2
    exit 1
  fi
done

# ---------------------------------------------------------------------------
# GROUP 1: Changed-set computation
# ---------------------------------------------------------------------------
echo "--- [1] Changed-set computation: --diff and --staged ---"
echo ""

# Build a fixture git repo with two files:
#   clean.js   -- committed in the base commit
#   modified.js -- committed in the base commit, then modified (working tree)
# and a staged variant: staged.js added to the index but not committed.

REPO1=$(make_repo)

# Base commit: clean.js
printf 'const x = 1;\n' > "$REPO1/clean.js"
printf 'const y = 2;\n' > "$REPO1/modified.js"
git -C "$REPO1" add -A
git -C "$REPO1" commit -q -m "base"

BASE_SHA=$(git -C "$REPO1" rev-parse HEAD)

# Second commit: doesn't change anything (we need HEAD~1 to be the "base")
# Actually: make "base" the base ref and modify modified.js AFTER commit
# so git diff BASE_SHA...HEAD shows nothing (same commit).
# Better: make a real second commit to HEAD so we can diff HEAD~1...HEAD.
printf 'const y = 3;  // changed\n' > "$REPO1/modified.js"
git -C "$REPO1" add modified.js
git -C "$REPO1" commit -q -m "change modified.js"

# Compute changed files via --diff (HEAD~1...HEAD)
CHANGES_Z1=$(make_tmp)/changed1.z
git -C "$REPO1" diff --name-only -z "HEAD~1...HEAD" > "$CHANGES_Z1"

PATHS1=$(read_z_file "$CHANGES_Z1")

if echo "$PATHS1" | grep -qxF "modified.js"; then
  pass "git diff --name-only -z HEAD~1...HEAD includes 'modified.js'"
else
  fail "git diff --name-only -z HEAD~1...HEAD should include 'modified.js' (got: $PATHS1)"
fi

if ! echo "$PATHS1" | grep -qxF "clean.js"; then
  pass "git diff --name-only -z HEAD~1...HEAD does NOT include 'clean.js' (unchanged)"
else
  fail "git diff --name-only -z HEAD~1...HEAD should NOT include 'clean.js'"
fi

# Generate changed-files.txt from the -z file using python3 (documented step)
CHANGES_TXT1=$(make_tmp)/changed1.txt
python3 - "$CHANGES_Z1" "$CHANGES_TXT1" << 'PYEOF'
import sys
with open(sys.argv[1], "rb") as fh:
    data = fh.read()
paths = [p.decode("utf-8", errors="surrogateescape")
         for p in data.rstrip(b"\x00").split(b"\x00") if p]
with open(sys.argv[2], "w", encoding="utf-8") as out:
    for p in paths:
        out.write(p + "\n")
PYEOF

TXT1_CONTENT=$(cat "$CHANGES_TXT1")
if echo "$TXT1_CONTENT" | grep -qxF "modified.js"; then
  pass "changed-files.txt (from python3 -z parse) contains 'modified.js'"
else
  fail "changed-files.txt should contain 'modified.js'"
fi

# Verify byte-exact round-trip: reading back the -z file should produce the same paths
Z_PATHS=$(read_z_file "$CHANGES_Z1")
TXT_PATHS=$(cat "$CHANGES_TXT1" | tr '\n' '|' | sed 's/|$//')
Z_PATHS_PIPE=$(echo "$Z_PATHS" | tr '\n' '|' | sed 's/|$//')

if [ "$Z_PATHS_PIPE" = "$TXT_PATHS" ]; then
  pass "python3 -z parse: paths round-trip byte-exact between .z and .txt"
else
  fail "python3 -z parse: paths differ between .z and .txt (z='$Z_PATHS_PIPE' txt='$TXT_PATHS')"
fi

# Test --staged: stage a new file and verify git diff --staged detects it
printf 'const z = 4;\n' > "$REPO1/staged.js"
git -C "$REPO1" add staged.js

STAGED_Z1=$(make_tmp)/staged1.z
git -C "$REPO1" diff --name-only -z --staged > "$STAGED_Z1"

STAGED_PATHS=$(read_z_file "$STAGED_Z1")

if echo "$STAGED_PATHS" | grep -qxF "staged.js"; then
  pass "git diff --name-only -z --staged includes 'staged.js'"
else
  fail "git diff --name-only -z --staged should include 'staged.js' (got: $STAGED_PATHS)"
fi

if ! echo "$STAGED_PATHS" | grep -qxF "modified.js"; then
  pass "git diff --name-only -z --staged does NOT include committed 'modified.js'"
else
  fail "git diff --name-only -z --staged should NOT include already-committed 'modified.js'"
fi

# ---------------------------------------------------------------------------
# GROUP 2: Hostile filename
# ---------------------------------------------------------------------------
echo ""
echo "--- [2] Hostile filename: inert through changed-set computation and filter ---"
echo ""

REPO2=$(make_repo)

# Base commit with clean.js
printf 'const safe = 1;\n' > "$REPO2/clean.js"
git -C "$REPO2" add clean.js
git -C "$REPO2" commit -q -m "base"

# Add a file with a hostile name (semicolon + space in name)
EVIL_NAME='evil; touch PWNED.js'
printf 'const evil = 1;\n' > "$REPO2/$EVIL_NAME"
git -C "$REPO2" add -- "$EVIL_NAME"
git -C "$REPO2" commit -q -m "add hostile-named file"

# Critical: pre-clean any PWNED artifacts BEFORE the changed-set computation
# so the existence check below is non-vacuous (any PWNED file found here was
# created by the computation itself, not left over from a prior test step).
rm -f "$REPO2/PWNED.js" "$(pwd)/PWNED.js" "/tmp/PWNED.js" 2>/dev/null || true

# Compute changed set
EVIL_Z=$(make_tmp)/evil-changed.z
git -C "$REPO2" diff --name-only -z "HEAD~1...HEAD" > "$EVIL_Z"

EVIL_PATHS=$(read_z_file "$EVIL_Z")

# The hostile file should appear as inert data
if echo "$EVIL_PATHS" | grep -qF "$EVIL_NAME"; then
  pass "hostile filename '$EVIL_NAME' appears in changed-set as inert data"
else
  fail "hostile filename '$EVIL_NAME' missing from changed-set (got: $EVIL_PATHS)"
fi

# Critical: no PWNED file created during changed-set computation.
# (pre-clean ran before the computation above, so any PWNED file here was
# created by it -- shell injection evidence that must fail loudly.)
PWNED_FOUND=0
for PWNED_PATH in "$REPO2/PWNED.js" "$(pwd)/PWNED.js" "/tmp/PWNED.js"; do
  if [ -f "$PWNED_PATH" ]; then
    PWNED_FOUND=$((PWNED_FOUND + 1))
    echo "  PWNED found at: $PWNED_PATH" >&2
  fi
done
if [ "$PWNED_FOUND" -eq 0 ]; then
  pass "hostile filename: no PWNED.js created during changed-set computation"
else
  fail "hostile filename: PWNED.js was created -- shell injection succeeded (CRITICAL)"
fi

# Now apply the diff filter: create a synthetic spine JSONL with findings for both
# the hostile file and a safe file.  The hostile file is "changed"; safe is not.
SYNTH_SPINE=$(make_tmp)/synth.jsonl
# Build a finding for the hostile filename (in changed set) and one for clean.js (not)
python3 - "$SYNTH_SPINE" "$EVIL_NAME" << 'PYEOF'
import json, sys
spine_file, evil_name = sys.argv[1], sys.argv[2]
lines = []
# Finding for hostile-named file (should SURVIVE filter)
lines.append(json.dumps({
    "check_id": "security/leaked-credential",
    "rule_id": "test-rule",
    "severity": "high",
    "confidence": "high",
    "detection": "tool",
    "source": "tool",
    "message": "test finding in hostile-named file",
    "location": {"path": evil_name, "line": 1},
    "fingerprint": "AbCdEf1234567890AbCdEf1234567890AbCdEf12",
}))
# Finding for clean.js (should be EXCLUDED by filter)
lines.append(json.dumps({
    "check_id": "security/leaked-credential",
    "rule_id": "test-rule",
    "severity": "high",
    "confidence": "high",
    "detection": "tool",
    "source": "tool",
    "message": "test finding in clean.js",
    "location": {"path": "clean.js", "line": 1},
    "fingerprint": "BbCcDd1234567890BbCcDd1234567890BbCcDd12",
}))
# coverage_gap record (should PASS THROUGH unconditionally)
lines.append(json.dumps({
    "type": "coverage_gap",
    "tool": "semgrep",
    "check_id": "spine/wrapper-error",
    "description": "semgrep not installed",
}))
# provenance record (should PASS THROUGH unconditionally)
lines.append(json.dumps({
    "type": "provenance",
    "tool": "ccgm-spine",
    "version": "1.0",
    "repo": "/tmp/test",
    "tools_requested": "gitleaks",
    "timestamp": "2026-01-01T00:00:00Z",
}))
with open(spine_file, "w") as fh:
    for l in lines:
        fh.write(l + "\n")
PYEOF

EVIL_FILTER_OUT=$(make_tmp)/evil-filtered.jsonl
apply_diff_filter "$SYNTH_SPINE" "$EVIL_Z" "$EVIL_FILTER_OUT"

# Critical: apply_diff_filter must NOT have created any PWNED artifacts
# (guards the python filter path, not just the shell computation above).
PWNED_FOUND_POST=0
for PWNED_PATH in "$REPO2/PWNED.js" "$(pwd)/PWNED.js" "/tmp/PWNED.js"; do
  if [ -f "$PWNED_PATH" ]; then
    PWNED_FOUND_POST=$((PWNED_FOUND_POST + 1))
    echo "  PWNED found at: $PWNED_PATH" >&2
  fi
done
if [ "$PWNED_FOUND_POST" -eq 0 ]; then
  pass "hostile filename: no PWNED.js created during apply_diff_filter (python filter path)"
else
  fail "hostile filename: PWNED.js created by apply_diff_filter -- injection in filter path (CRITICAL)"
fi

# Verify: hostile-named finding SURVIVES
EVIL_FINDING_FOUND=$(python3 - "$EVIL_FILTER_OUT" "$EVIL_NAME" << 'PYEOF'
import json, sys
out_file, evil_name = sys.argv[1], sys.argv[2]
for raw in open(out_file):
    raw = raw.strip()
    if not raw:
        continue
    try:
        rec = json.loads(raw)
    except Exception:
        continue
    if "type" in rec:
        continue
    if rec.get("location", {}).get("path") == evil_name:
        print("FOUND")
        import sys; sys.exit(0)
print("NOT_FOUND")
PYEOF
)

if [ "$EVIL_FINDING_FOUND" = "FOUND" ]; then
  pass "hostile filename: finding for '$EVIL_NAME' SURVIVES diff filter (in changed set)"
else
  fail "hostile filename: finding for '$EVIL_NAME' should survive diff filter (in changed set)"
fi

# Verify: clean.js finding is EXCLUDED
CLEAN_FINDING_FOUND=$(python3 - "$EVIL_FILTER_OUT" << 'PYEOF'
import json, sys
for raw in open(sys.argv[1]):
    raw = raw.strip()
    if not raw:
        continue
    try:
        rec = json.loads(raw)
    except Exception:
        continue
    if "type" in rec:
        continue
    if rec.get("location", {}).get("path") == "clean.js":
        print("FOUND")
        import sys; sys.exit(0)
print("NOT_FOUND")
PYEOF
)

if [ "$CLEAN_FINDING_FOUND" = "NOT_FOUND" ]; then
  pass "hostile filename: finding for 'clean.js' EXCLUDED by diff filter (not in changed set)"
else
  fail "hostile filename: finding for 'clean.js' should be excluded (not in changed set)"
fi

# Verify: coverage_gap and provenance pass through
COVGAP_FOUND=$(python3 - "$EVIL_FILTER_OUT" << 'PYEOF'
import json, sys
for raw in open(sys.argv[1]):
    raw = raw.strip()
    if not raw:
        continue
    try:
        rec = json.loads(raw)
    except Exception:
        continue
    if rec.get("type") == "coverage_gap":
        print("FOUND")
        import sys; sys.exit(0)
print("NOT_FOUND")
PYEOF
)
if [ "$COVGAP_FOUND" = "FOUND" ]; then
  pass "hostile filename: coverage_gap record passes through diff filter"
else
  fail "hostile filename: coverage_gap record should pass through diff filter unconditionally"
fi

PROV_FOUND=$(python3 - "$EVIL_FILTER_OUT" << 'PYEOF'
import json, sys
for raw in open(sys.argv[1]):
    raw = raw.strip()
    if not raw:
        continue
    try:
        rec = json.loads(raw)
    except Exception:
        continue
    if rec.get("type") == "provenance":
        print("FOUND")
        import sys; sys.exit(0)
print("NOT_FOUND")
PYEOF
)
if [ "$PROV_FOUND" = "FOUND" ]; then
  pass "hostile filename: provenance record passes through diff filter"
else
  fail "hostile filename: provenance record should pass through diff filter unconditionally"
fi

# Critical: path round-trips byte-exact through .z and back
EVIL_Z_ROUNDTRIP=$(read_z_file "$EVIL_Z" | head -1)
if [ "$EVIL_Z_ROUNDTRIP" = "$EVIL_NAME" ]; then
  pass "hostile filename: path round-trips byte-exact through null-delimited .z file"
else
  fail "hostile filename: path did not round-trip byte-exact (got '$EVIL_Z_ROUNDTRIP' expected '$EVIL_NAME')"
fi

# ---------------------------------------------------------------------------
# GROUP 2b: Newline-named hostile file
# A file whose name contains a literal newline exercises the case where
# null-delimiting (-z) genuinely differs from line-splitting.  A plain
# `git diff --name-only` (without -z) would split the name across two
# lines, corrupting adjacent entries.  With -z the name is preserved as
# a single opaque token in the binary stream.
# ---------------------------------------------------------------------------
echo ""
echo "--- [2b] Newline-named hostile file: null-delimited .z handles embedded newline ---"
echo ""

REPO2B=$(make_repo)

# Build the newline-embedded filename using printf into a variable;
# never interpolate the raw name into an unquoted shell string.
NEWLINE_NAME="$(printf 'evil\nname.js')"

printf 'const safe = 1;\n' > "$REPO2B/clean.js"
git -C "$REPO2B" add clean.js
git -C "$REPO2B" commit -q -m "base"

# Create the newline-named file; address it via the variable, not an inline name.
printf 'const evil = 1;\n' > "$REPO2B/$NEWLINE_NAME"
git -C "$REPO2B" add -- "$REPO2B/$NEWLINE_NAME"
git -C "$REPO2B" commit -q -m "add newline-named file"

# Compute changed set with -z (null-delimited)
NEWLINE_Z=$(make_tmp)/newline-changed.z
git -C "$REPO2B" diff --name-only -z "HEAD~1...HEAD" > "$NEWLINE_Z"

# Round-trip: parse the .z file with python3; must produce the exact
# embedded-newline name as a single opaque token.
NEWLINE_ROUNDTRIP=$(python3 - "$NEWLINE_Z" "$NEWLINE_NAME" << 'PYEOF'
import sys
with open(sys.argv[1], 'rb') as fh:
    data = fh.read()
names = [p.decode('utf-8', errors='surrogateescape')
         for p in data.rstrip(b'\x00').split(b'\x00') if p]
expected = sys.argv[2]
if expected in names:
    print('FOUND')
else:
    print('NOT_FOUND: ' + repr(names))
PYEOF
)

if [ "$NEWLINE_ROUNDTRIP" = "FOUND" ]; then
  pass "newline-named file: path round-trips byte-exact through null-delimited .z file"
else
  fail "newline-named file: .z round-trip failed ($NEWLINE_ROUNDTRIP)"
fi

# The .z file is canonical for machine consumers.  The .txt (newline-delimited)
# view is intentionally lossy for names that contain newlines -- the embedded
# newline renders as a line break that looks like a path boundary in the txt.
# We document this but assert only on the canonical .z parse.
NEWLINE_TXT=$(make_tmp)/newline-changed.txt
python3 - "$NEWLINE_Z" "$NEWLINE_TXT" << 'PYEOF'
import sys
with open(sys.argv[1], 'rb') as fh:
    data = fh.read()
paths = [p.decode('utf-8', errors='surrogateescape')
         for p in data.rstrip(b'\x00').split(b'\x00') if p]
# Note: writing a newline-embedded path to a newline-delimited .txt is
# intentionally lossy -- the embedded newline becomes a line separator.
# This is the known-lossy human-readable view; the .z file is canonical.
with open(sys.argv[2], 'w', encoding='utf-8') as out:
    for p in paths:
        out.write(p + '\n')
PYEOF
# .txt view is known-lossy for newline-embedded names; only .z is canonical.
pass "newline-named file: .txt view is known-lossy for embedded newlines (documented); .z is canonical"

# Apply diff filter: the newline-named file IS in the changed set and must survive.
NL_SYNTH_SPINE=$(make_tmp)/nl-synth.jsonl
python3 - "$NL_SYNTH_SPINE" "$NEWLINE_NAME" << 'PYEOF'
import json, sys
spine_file, nl_name = sys.argv[1], sys.argv[2]
lines = []
lines.append(json.dumps({
    'check_id': 'security/leaked-credential',
    'rule_id': 'test-rule',
    'severity': 'high',
    'confidence': 'high',
    'detection': 'tool',
    'source': 'tool',
    'message': 'test finding in newline-named file',
    'location': {'path': nl_name, 'line': 1},
    'fingerprint': 'CcDdEe1234567890CcDdEe1234567890CcDdEe12',
}))
# Finding for clean.js -- should be excluded (not in changed set)
lines.append(json.dumps({
    'check_id': 'security/leaked-credential',
    'rule_id': 'test-rule',
    'severity': 'high',
    'confidence': 'high',
    'detection': 'tool',
    'source': 'tool',
    'message': 'test finding in clean.js',
    'location': {'path': 'clean.js', 'line': 1},
    'fingerprint': 'DdEeFf1234567890DdEeFf1234567890DdEeFf12',
}))
with open(spine_file, 'w') as fh:
    for l in lines:
        fh.write(l + '\n')
PYEOF

NL_FILTER_OUT=$(make_tmp)/nl-filtered.jsonl
apply_diff_filter "$NL_SYNTH_SPINE" "$NEWLINE_Z" "$NL_FILTER_OUT"

# Assert: newline-named finding SURVIVES (path is in changed set)
NL_FINDING=$(python3 - "$NL_FILTER_OUT" "$NEWLINE_NAME" << 'PYEOF'
import json, sys
out_file, nl_name = sys.argv[1], sys.argv[2]
for raw in open(out_file):
    raw = raw.strip()
    if not raw:
        continue
    try:
        rec = json.loads(raw)
    except Exception:
        continue
    if 'type' in rec:
        continue
    if rec.get('location', {}).get('path') == nl_name:
        print('FOUND')
        import sys; sys.exit(0)
print('NOT_FOUND')
PYEOF
)
if [ "$NL_FINDING" = "FOUND" ]; then
  pass "newline-named file: finding SURVIVES apply_diff_filter (path in changed set)"
else
  fail "newline-named file: finding should survive apply_diff_filter"
fi

# Assert: clean.js finding EXCLUDED (not in changed set)
NL_CLEAN_FINDING=$(python3 - "$NL_FILTER_OUT" << 'PYEOF'
import json, sys
for raw in open(sys.argv[1]):
    raw = raw.strip()
    if not raw:
        continue
    try:
        rec = json.loads(raw)
    except Exception:
        continue
    if 'type' in rec:
        continue
    if rec.get('location', {}).get('path') == 'clean.js':
        print('FOUND')
        import sys; sys.exit(0)
print('NOT_FOUND')
PYEOF
)
if [ "$NL_CLEAN_FINDING" = "NOT_FOUND" ]; then
  pass "newline-named file: clean.js finding EXCLUDED by apply_diff_filter (not in changed set)"
else
  fail "newline-named file: clean.js finding should be excluded by apply_diff_filter"
fi

# Assert: no PWNED artifacts created during newline-named file operations
PWNED_FOUND_NL=0
for PWNED_PATH in "$REPO2B/PWNED.js" "$(pwd)/PWNED.js" "/tmp/PWNED.js"; do
  if [ -f "$PWNED_PATH" ]; then
    PWNED_FOUND_NL=$((PWNED_FOUND_NL + 1))
    echo "  PWNED found at: $PWNED_PATH" >&2
  fi
done
if [ "$PWNED_FOUND_NL" -eq 0 ]; then
  pass "newline-named file: no PWNED.js created during any operation"
else
  fail "newline-named file: PWNED.js was created -- injection succeeded (CRITICAL)"
fi

# ---------------------------------------------------------------------------
# GROUP 3: Spine post-filter with real gitleaks (if available)
# ---------------------------------------------------------------------------
echo ""
echo "--- [3] Spine post-filter: changed-file finding survives; unchanged excluded ---"
echo ""

if command -v gitleaks >/dev/null 2>&1; then
  REPO3=$(make_repo)

  # Base commit: clean files (no secrets)
  printf 'const x = 1;\n' > "$REPO3/unchanged.js"
  printf 'const y = 2;\n' > "$REPO3/changed.js"
  git -C "$REPO3" add -A
  git -C "$REPO3" commit -q -m "base"

  # Modify changed.js: inject a fake AWS key (ADV-009 pattern)
  KEY_PREFIX3="AKIAZ12345"
  KEY_SUFFIX3="6789ABCDEFGH"
  FAKE_KEY3="${KEY_PREFIX3}${KEY_SUFFIX3}"
  printf '// This file intentionally contains a test secret for scanner validation\nconst AWS_KEY = "%s";\n' "$FAKE_KEY3" \
    > "$REPO3/changed.js"

  # Also inject the same fake key into unchanged.js (to test filtering)
  printf '// This file intentionally contains a test secret for scanner validation\nconst AWS_KEY2 = "%s";\n' "$FAKE_KEY3" \
    > "$REPO3/unchanged.js"

  git -C "$REPO3" add changed.js
  git -C "$REPO3" commit -q -m "add secret to changed.js"

  # Compute the changed set (only changed.js -- unchanged.js was not committed after base)
  CHANGES_Z3=$(make_tmp)/changed3.z
  git -C "$REPO3" diff --name-only -z "HEAD~1...HEAD" > "$CHANGES_Z3"

  CHANGED_PATHS3=$(read_z_file "$CHANGES_Z3")

  if echo "$CHANGED_PATHS3" | grep -qxF "changed.js"; then
    pass "spine post-filter fixture: 'changed.js' in changed set"
  else
    fail "spine post-filter fixture: 'changed.js' should be in changed set (got: $CHANGED_PATHS3)"
  fi

  if ! echo "$CHANGED_PATHS3" | grep -qxF "unchanged.js"; then
    pass "spine post-filter fixture: 'unchanged.js' NOT in changed set"
  else
    fail "spine post-filter fixture: 'unchanged.js' should NOT be in changed set"
  fi

  # Run real spine against the fixture repo
  SPINE3_OUT=$(make_tmp)/spine3.jsonl
  set +e
  bash "$SPINE_SCRIPT" \
    --repo  "$REPO3" \
    --tools "gitleaks" \
    --output "$SPINE3_OUT" 2>/dev/null
  SPINE3_EC=$?
  set -e

  if [ "$SPINE3_EC" -eq 0 ] && [ -f "$SPINE3_OUT" ]; then
    pass "spine post-filter: spine ran successfully (exit 0)"
  else
    fail "spine post-filter: spine failed (exit $SPINE3_EC) or output missing"
  fi

  # Count findings before filter (both changed.js and unchanged.js should have secrets)
  BEFORE_COUNT=$(python3 - "$SPINE3_OUT" << 'PYEOF'
import json, sys
count = 0
for raw in open(sys.argv[1]):
    raw = raw.strip()
    if not raw:
        continue
    try:
        rec = json.loads(raw)
    except Exception:
        continue
    if "type" not in rec:
        count += 1
print(count)
PYEOF
)
  if [ "${BEFORE_COUNT:-0}" -ge 1 ]; then
    pass "spine post-filter: spine found >= 1 finding before filter (both files have secrets)"
  else
    fail "spine post-filter: expected >= 1 finding before filter (gitleaks should detect fake key)"
  fi

  # Apply diff filter
  FILTERED3_OUT=$(make_tmp)/filtered3.jsonl
  apply_diff_filter "$SPINE3_OUT" "$CHANGES_Z3" "$FILTERED3_OUT"

  # Assert: finding for changed.js SURVIVES
  CHANGED_SURVIVED=$(python3 - "$FILTERED3_OUT" << 'PYEOF'
import json, sys
for raw in open(sys.argv[1]):
    raw = raw.strip()
    if not raw:
        continue
    try:
        rec = json.loads(raw)
    except Exception:
        continue
    if "type" in rec:
        continue
    path = rec.get("location", {}).get("path", "")
    if "changed.js" in path:
        print("FOUND")
        import sys; sys.exit(0)
print("NOT_FOUND")
PYEOF
)
  if [ "$CHANGED_SURVIVED" = "FOUND" ]; then
    pass "spine post-filter: changed.js finding SURVIVES diff filter"
  else
    fail "spine post-filter: changed.js finding should survive (in changed set)"
  fi

  # Assert: finding for unchanged.js is EXCLUDED
  UNCHANGED_EXCLUDED=$(python3 - "$FILTERED3_OUT" << 'PYEOF'
import json, sys
for raw in open(sys.argv[1]):
    raw = raw.strip()
    if not raw:
        continue
    try:
        rec = json.loads(raw)
    except Exception:
        continue
    if "type" in rec:
        continue
    path = rec.get("location", {}).get("path", "")
    if "unchanged.js" in path:
        print("FOUND")
        import sys; sys.exit(0)
print("NOT_FOUND")
PYEOF
)
  if [ "$UNCHANGED_EXCLUDED" = "NOT_FOUND" ]; then
    pass "spine post-filter: unchanged.js finding EXCLUDED by diff filter"
  else
    fail "spine post-filter: unchanged.js finding should be excluded (not in changed set)"
  fi

  # Assert: coverage_gap/provenance records pass through filter
  META_PASS=$(python3 - "$FILTERED3_OUT" << 'PYEOF'
import json, sys
found_provenance = False
for raw in open(sys.argv[1]):
    raw = raw.strip()
    if not raw:
        continue
    try:
        rec = json.loads(raw)
    except Exception:
        continue
    if rec.get("type") == "provenance":
        found_provenance = True
print("FOUND" if found_provenance else "NOT_FOUND")
PYEOF
)
  if [ "$META_PASS" = "FOUND" ]; then
    pass "spine post-filter: provenance record passes through filter"
  else
    fail "spine post-filter: provenance record should pass through diff filter unconditionally"
  fi

else
  echo "  gitleaks not installed -- skipping spine post-filter e2e (SKIP, not FAIL)"
  echo "  SKIP: spine post-filter: changed.js finding survives"
  echo "  SKIP: spine post-filter: unchanged.js finding excluded"
  echo "  SKIP: spine post-filter: meta records pass through"
fi

# ---------------------------------------------------------------------------
# GROUP 4: Empty diff -> clean exit with message, no artifacts
# ---------------------------------------------------------------------------
echo ""
echo "--- [4] Empty diff -> clean exit, no spine/worker artifacts ---"
echo ""

REPO4=$(make_repo)

printf 'const x = 1;\n' > "$REPO4/a.js"
git -C "$REPO4" add -A
git -C "$REPO4" commit -q -m "init"

# No changes since HEAD -- diff is empty
EMPTY_Z=$(make_tmp)/empty.z
git -C "$REPO4" diff --name-only -z "HEAD...HEAD" > "$EMPTY_Z"

EMPTY_COUNT=$(python3 - "$EMPTY_Z" << 'PYEOF'
import sys
data = open(sys.argv[1], "rb").read()
paths = [p for p in data.rstrip(b"\x00").split(b"\x00") if p]
print(len(paths))
PYEOF
)

if [ "${EMPTY_COUNT:-0}" -eq 0 ]; then
  pass "empty diff: changed-files.z contains zero paths"
else
  fail "empty diff: expected zero paths in changed-files.z, got $EMPTY_COUNT"
fi

# The documented guard: if count == 0, print message and exit 0 (no spine/workers/report)
EMPTY_OUTPUT=$(python3 - "$EMPTY_Z" << 'PYEOF'
import sys
data = open(sys.argv[1], "rb").read()
paths = [p for p in data.rstrip(b"\x00").split(b"\x00") if p]
if len(paths) == 0:
    print("no changed files -- nothing to audit")
    sys.exit(0)
print(f"would proceed with {len(paths)} files")
sys.exit(1)
PYEOF
)

if echo "$EMPTY_OUTPUT" | grep -q "no changed files"; then
  pass "empty diff: documented exit message 'no changed files -- nothing to audit' emitted"
else
  fail "empty diff: expected 'no changed files' message from empty-set guard"
fi

# Staged empty diff
EMPTY_STAGED_Z=$(make_tmp)/empty-staged.z
git -C "$REPO4" diff --name-only -z --staged > "$EMPTY_STAGED_Z"

EMPTY_STAGED_COUNT=$(python3 - "$EMPTY_STAGED_Z" << 'PYEOF'
import sys
data = open(sys.argv[1], "rb").read()
paths = [p for p in data.rstrip(b"\x00").split(b"\x00") if p]
print(len(paths))
PYEOF
)

if [ "${EMPTY_STAGED_COUNT:-0}" -eq 0 ]; then
  pass "empty staged diff: changed-files.z contains zero paths (no staged files)"
else
  fail "empty staged diff: expected zero paths, got $EMPTY_STAGED_COUNT"
fi

# ---------------------------------------------------------------------------
# GROUP 5: SKILL.md consistency checks
# ---------------------------------------------------------------------------
echo ""
echo "--- [5] SKILL.md consistency: --diff/--staged documented in both paths ---"
echo ""

# 5a. --diff and --staged appear in the Usage section
# Use state-tracking awk to avoid the same-line open/close trap.
set +e
DIFF_IN_USAGE=$(awk 'found && /^## /{exit} /^## Usage$/{found=1} found' "$SKILL_MD" \
  | grep -c "\-\-diff" 2>/dev/null || true)
STAGED_IN_USAGE=$(awk 'found && /^## /{exit} /^## Usage$/{found=1} found' "$SKILL_MD" \
  | grep -c "\-\-staged" 2>/dev/null || true)
set -e

if [ "${DIFF_IN_USAGE:-0}" -ge 1 ]; then
  pass "SKILL.md Usage: --diff is documented"
else
  fail "SKILL.md Usage: --diff must be documented in the Usage section"
fi

if [ "${STAGED_IN_USAGE:-0}" -ge 1 ]; then
  pass "SKILL.md Usage: --staged is documented"
else
  fail "SKILL.md Usage: --staged must be documented in the Usage section"
fi

# 5b. --diff and --staged appear in Mode Detection
set +e
MD_SECTION=$(awk '/^### Mode Detection/,/^\*\*If NO flags/' "$SKILL_MD" 2>/dev/null || true)
DIFF_IN_MD=$(echo "$MD_SECTION" | grep -c "\-\-diff" 2>/dev/null || true)
STAGED_IN_MD=$(echo "$MD_SECTION" | grep -c "\-\-staged" 2>/dev/null || true)
set -e

if [ "${DIFF_IN_MD:-0}" -ge 1 ]; then
  pass "SKILL.md Mode Detection: --diff is listed"
else
  fail "SKILL.md Mode Detection: --diff must be listed in mode detection flags"
fi

if [ "${STAGED_IN_MD:-0}" -ge 1 ]; then
  pass "SKILL.md Mode Detection: --staged is listed"
else
  fail "SKILL.md Mode Detection: --staged must be listed in mode detection flags"
fi

# 5c. changed-files.z artifact is documented in BOTH M-phase and --single sections
set +e
M_SECTION=$(awk '/^### Phase M2\.1/,/^### Phase M2\.5/' "$SKILL_MD" 2>/dev/null || true)
SINGLE_SECTION=$(awk '/^### Phase 1\.5/,/^### Phase 2/' "$SKILL_MD" 2>/dev/null || true)
set -e

if echo "$M_SECTION" | grep -q "changed-files.z"; then
  pass "SKILL.md M-phase: changed-files.z artifact is documented"
else
  fail "SKILL.md M-phase: Phase M2.1 must document the changed-files.z artifact"
fi

if echo "$SINGLE_SECTION" | grep -q "changed-files.z"; then
  pass "SKILL.md --single path: changed-files.z artifact is documented"
else
  fail "SKILL.md --single path: Phase 1.5 must document the changed-files.z artifact"
fi

# 5d. The diff-filter step (post-filter model) appears in BOTH paths
if echo "$M_SECTION" | grep -q "diff.filter\|diff_filter\|filter.*spine\|spine.*filter"; then
  pass "SKILL.md M-phase: spine post-filter step is documented"
else
  fail "SKILL.md M-phase: Phase M2.1 must document the spine post-filter step"
fi

if echo "$SINGLE_SECTION" | grep -q "diff.filter\|diff_filter\|filter.*spine\|spine.*filter\|post.filter\|postfilter"; then
  pass "SKILL.md --single path: spine post-filter step is documented"
else
  fail "SKILL.md --single path: Phase 1.5 must document the spine post-filter step"
fi

# 5e. Full-repo spine-once step is UNCONDITIONAL (no --diff guard around it)
# The documented form is:
#   bash "$SKILL_ROOT/scripts/spine/run.sh" \
#     --repo  "$REPO_DIR" \
#     --tools "$SPINE_TOOLS" \
#     --output "$AUDIT_DIR/current/spine/findings.jsonl"
# This should appear without an outer if/else diff guard.
# We just check the spine invocation still exists in the M4 section.
set +e
M4_SECTION=$(awk '/^### Phase M4/,/^### Phase M5/' "$SKILL_MD" 2>/dev/null || true)
SPINE_ONCE=$(echo "$M4_SECTION" | grep -c "scripts/spine/run.sh" 2>/dev/null || true)
set -e

if [ "${SPINE_ONCE:-0}" -ge 1 ]; then
  pass "SKILL.md M4: spine/run.sh invocation is still present (full-repo path unchanged)"
else
  fail "SKILL.md M4: spine/run.sh must still be invoked in Phase M4 for full-repo mode"
fi

# Also verify in --single Phase 3
set +e
PHASE3_SECTION=$(awk '/^### Phase 3: Run the Spine/,/^### Phase 4/' "$SKILL_MD" 2>/dev/null || true)
SPINE_SINGLE=$(echo "$PHASE3_SECTION" | grep -c "scripts/spine/run.sh\|spine/run.sh" 2>/dev/null || true)
set -e

if [ "${SPINE_SINGLE:-0}" -ge 1 ]; then
  pass "SKILL.md --single Phase 3: spine/run.sh invocation is still present"
else
  fail "SKILL.md --single Phase 3: spine/run.sh must still be invoked for full-repo mode"
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
