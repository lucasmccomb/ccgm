#!/usr/bin/env bash
# CCGM audit -- test-exclusion.sh
# Tests for field-report #1: path-exclusion discipline in the spine.
#
#   1. spine on a repo containing node_modules/, .claude/worktrees/, and dist/
#      copies of a fake key emits findings ONLY from real source paths.
#   2. exclude.py --filter drops junk-path findings and passes through
#      type records (provenance/coverage_gap) untouched.
#   3. exclude.py --gitleaks-config writes a config that allowlists the
#      canonical excluded dirs.
#
# ADV-009: the fake secret is CONSTRUCTED AT RUNTIME from fragments; the
# assembled string never appears in this tracked file.
#
# Usage: bash modules/commands-extra/skills/audit/tests/test-exclusion.sh
# Exit:  0 = all passed, non-zero = at least one failure

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SPINE_DIR="$SCRIPT_DIR/../scripts/spine"
RUN_SH="$SPINE_DIR/run.sh"
EXCLUDE_PY="$SPINE_DIR/exclude.py"

PASS=0
FAIL=0
ERRORS=()

pass() { printf '  [PASS] %s\n' "$1"; PASS=$((PASS + 1)); }
fail() { printf '  [FAIL] %s\n' "$1"; ERRORS+=("$1"); FAIL=$((FAIL + 1)); }

TESTRUN_DIR="$(mktemp -d /tmp/ccgm-test-exclusion-XXXXXX)"
trap 'rm -rf "$TESTRUN_DIR"' EXIT

# ---------------------------------------------------------------------------
# Test 1: spine ignores node_modules / worktree / dist copies (live gitleaks)
# ---------------------------------------------------------------------------
printf '\nTest 1: spine emits 0 findings from excluded dirs\n'

if ! command -v gitleaks > /dev/null 2>&1; then
  pass "gitleaks not installed -- live exclusion test skipped"
else
  REPO="$TESTRUN_DIR/repo"
  mkdir -p "$REPO/src" \
           "$REPO/node_modules/evil" \
           "$REPO/.claude/worktrees/copy/src" \
           "$REPO/dist"

  # Assemble a detectable fake AWS key from fragments at runtime (ADV-009).
  KEY_PART1="AKIA"
  KEY_PART2="ABCDEFGHIJKLMNOP"
  FAKE_KEY="${KEY_PART1}${KEY_PART2}"

  for rel in src/config.env \
             node_modules/evil/leak.env \
             .claude/worktrees/copy/src/config.env \
             dist/bundle.env; do
    python3 - "$REPO/$rel" "$FAKE_KEY" << 'PYEOF'
import sys
path, key = sys.argv[1], sys.argv[2]
with open(path, "w") as fh:
    fh.write("AWS_ACCESS_KEY_ID=" + key + "\n")
PYEOF
  done

  OUT="$TESTRUN_DIR/out.jsonl"
  set +e
  bash "$RUN_SH" --repo "$REPO" --tools gitleaks --output "$OUT" 2>"$TESTRUN_DIR/stderr.txt"
  RUN_EXIT=$?
  set -e

  if [[ $RUN_EXIT -eq 0 ]]; then
    pass "t1: spine exits 0"
  else
    fail "t1: spine exits $RUN_EXIT (expected 0)"
  fi

  # Count findings whose path is in an excluded dir vs. real source.
  EXCLUDED_HITS="$(python3 - "$OUT" << 'PYEOF'
import json, sys
bad = 0
excluded_markers = ("node_modules/", ".claude/", "dist/")
for line in open(sys.argv[1]):
    line = line.strip()
    if not line:
        continue
    obj = json.loads(line)
    if "type" in obj:
        continue
    path = obj.get("location", {}).get("path", "")
    if any(m in path for m in excluded_markers):
        bad += 1
print(bad)
PYEOF
)"
  if [[ "$EXCLUDED_HITS" -eq 0 ]]; then
    pass "t1: zero findings from node_modules/.claude/dist"
  else
    fail "t1: $EXCLUDED_HITS finding(s) leaked from excluded dirs (expected 0)"
  fi

  REAL_HITS="$(python3 - "$OUT" << 'PYEOF'
import json, sys
good = 0
for line in open(sys.argv[1]):
    line = line.strip()
    if not line:
        continue
    obj = json.loads(line)
    if "type" in obj:
        continue
    path = obj.get("location", {}).get("path", "")
    if path == "src/config.env":
        good += 1
print(good)
PYEOF
)"
  if [[ "$REAL_HITS" -ge 1 ]]; then
    pass "t1: real source finding (src/config.env) still detected"
  else
    fail "t1: real source finding missing (expected >= 1 from src/config.env)"
  fi

  # The filter summary should appear on stderr (observability).
  if grep -q "filter-excluded:" "$TESTRUN_DIR/stderr.txt"; then
    pass "t1: post-filter summary printed to stderr"
  else
    fail "t1: no filter-excluded summary on stderr"
  fi

  # Per-tool progress line (#6) should appear on stderr.
  if grep -q "spine: gitleaks" "$TESTRUN_DIR/stderr.txt"; then
    pass "t1: per-tool progress line printed to stderr"
  else
    fail "t1: no per-tool progress line on stderr"
  fi
fi

# ---------------------------------------------------------------------------
# Test 2: exclude.py --filter drops junk findings, keeps type records + real
# ---------------------------------------------------------------------------
printf '\nTest 2: exclude.py --filter\n'

FIN="$TESTRUN_DIR/in.jsonl"
FOUT="$TESTRUN_DIR/filtered.jsonl"
python3 - "$FIN" << 'PYEOF'
import json, sys
recs = [
    {"type": "provenance", "tool": "ccgm-spine"},
    {"type": "coverage_gap", "tool": "knip", "check_id": "x/y", "description": "skip"},
    {"check_id": "a/b", "rule_id": "r", "severity": "low", "confidence": "low",
     "detection": "tool", "source": "tool", "message": "real",
     "location": {"path": "src/app.ts", "line": 1}, "fingerprint": "deadbeef0011:1"},
    {"check_id": "a/b", "rule_id": "r", "severity": "low", "confidence": "low",
     "detection": "tool", "source": "tool", "message": "junk nm",
     "location": {"path": "node_modules/pkg/index.js", "line": 1}, "fingerprint": "deadbeef0022:1"},
    {"check_id": "a/b", "rule_id": "r", "severity": "low", "confidence": "low",
     "detection": "tool", "source": "tool", "message": "junk worktree",
     "location": {"path": ".claude/worktrees/c/src/app.ts", "line": 1}, "fingerprint": "deadbeef0033:1"},
]
with open(sys.argv[1], "w") as fh:
    for r in recs:
        fh.write(json.dumps(r) + "\n")
PYEOF

set +e
FILTER_STDERR="$(python3 "$EXCLUDE_PY" --filter "$FIN" "$FOUT" 2>&1)"
FILTER_EXIT=$?
set -e

if [[ $FILTER_EXIT -eq 0 ]]; then
  pass "t2: filter exits 0"
else
  fail "t2: filter exits $FILTER_EXIT (expected 0)"
fi

KEPT_FINDINGS="$(python3 - "$FOUT" << 'PYEOF'
import json, sys
paths = []
for line in open(sys.argv[1]):
    line = line.strip()
    if not line:
        continue
    obj = json.loads(line)
    if "type" not in obj:
        paths.append(obj["location"]["path"])
print(",".join(paths))
PYEOF
)"
if [[ "$KEPT_FINDINGS" == "src/app.ts" ]]; then
  pass "t2: only the real-source finding survives ($KEPT_FINDINGS)"
else
  fail "t2: kept findings='$KEPT_FINDINGS' (expected 'src/app.ts')"
fi

TYPE_RECS="$(python3 - "$FOUT" << 'PYEOF'
import json, sys
n = 0
for line in open(sys.argv[1]):
    line = line.strip()
    if not line:
        continue
    if "type" in json.loads(line):
        n += 1
print(n)
PYEOF
)"
if [[ "$TYPE_RECS" -eq 2 ]]; then
  pass "t2: provenance + coverage_gap pass through (2 type records)"
else
  fail "t2: $TYPE_RECS type records survived (expected 2)"
fi

if echo "$FILTER_STDERR" | grep -q "dropped 2 junk-path"; then
  pass "t2: stderr reports dropped count (2)"
else
  fail "t2: stderr drop count wrong (got: $FILTER_STDERR)"
fi

# ---------------------------------------------------------------------------
# Test 3: exclude.py --gitleaks-config
# ---------------------------------------------------------------------------
printf '\nTest 3: exclude.py --gitleaks-config\n'

CFG="$TESTRUN_DIR/gl.toml"
set +e
python3 "$EXCLUDE_PY" --gitleaks-config "$CFG"
CFG_EXIT=$?
set -e

if [[ $CFG_EXIT -eq 0 && -s "$CFG" ]]; then
  pass "t3: config written"
else
  fail "t3: config not written (exit $CFG_EXIT)"
fi

if grep -q "useDefault = true" "$CFG"; then
  pass "t3: config keeps the default ruleset"
else
  fail "t3: config missing [extend] useDefault = true"
fi

if grep -q "node_modules" "$CFG" && grep -q 'allowlist' "$CFG"; then
  pass "t3: config allowlists node_modules"
else
  fail "t3: config does not allowlist node_modules"
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
