#!/usr/bin/env bash
# CCGM audit spine -- exclude/scope regression test (issue #726)
#
# Builds a tiny fixture repo containing:
#   - a real source file with one genuine eqeqeq violation (tracked)
#   - a .audit/worktrees/x.js copy (untracked, NOT gitignored)
#   - a dist/app.min.js minified file (gitignored)
#   - a committed public/vendor/lib.min.js vendored file (tracked)
#   - a gitignored .env.local with a fake API key
#
# Runs scripts/spine/run.sh --tools eslint,semgrep,gitleaks and asserts:
#   - exactly the ONE real source finding is reported
#     (no findings under .audit/, dist/, public/vendor, or *.min.js)
#   - gitleaks does NOT emit a leaked-credential finding for .env.local
#
# Exit code: 0 = all tests passed, 1 = failure
#
# This test FAILS on main (eslint lints the generated/vendored copies and
# gitleaks flags the gitignored .env.local) and PASSES after the spine-scope fix.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SPINE_DIR="$SCRIPT_DIR/../scripts/spine"

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
# eslint is required to surface the real finding. Without it the "exactly one
# finding" assertion is meaningless -- skip the whole test gracefully.
# ---------------------------------------------------------------------------
if ! command -v eslint > /dev/null 2>&1; then
  printf 'eslint not installed -- spine-scope regression test skipped.\n'
  exit 0
fi
if ! command -v git > /dev/null 2>&1; then
  printf 'git not installed -- spine-scope regression test skipped.\n'
  exit 0
fi

# ---------------------------------------------------------------------------
# Build the fixture repo
# ---------------------------------------------------------------------------
# Resolve symlinks (macOS /tmp -> /private/tmp) so the path eslint reports
# matches the repo_root the parser strips -- otherwise location.path stays
# absolute and the path assertions test the symlink quirk, not the scoping.
TESTRUN_TMPDIR="$(cd "$(mktemp -d /tmp/ccgm-excludes-XXXXXX)" && pwd -P)"
trap 'rm -rf "$TESTRUN_TMPDIR"' EXIT

FIX="$TESTRUN_TMPDIR/repo"
mkdir -p "$FIX/src" "$FIX/dist" "$FIX/client/public/jsdos" "$FIX/.audit/worktrees"

# Real, tracked source with a genuine eqeqeq violation.
cat > "$FIX/src/real.js" <<'EOF'
function check(a, b) {
  if (a == b) {
    return true;
  }
  return false;
}
EOF

# Audit-internal coordination copy (untracked, NOT gitignored). eqeqeq present.
cat > "$FIX/.audit/worktrees/x.js" <<'EOF'
function check(a, b) {
  if (a == b) {
    return true;
  }
  return false;
}
EOF

# Generated, gitignored, minified file under an excluded dir (single long line with ==).
printf 'var a=1,b=2,c=3,d=4,e=5,f=6,g=7,h=8,i=9,j=10;function z(){if(a==b){return c==d}return e==f}var k=z();console.log(k==g);\n' > "$FIX/dist/app.min.js"

# Vendored-but-committed minified file NOT under any excluded directory name
# (mirrors the lem-work client/public/js-dos/*.min.js case). Only the *.min.js
# file-glob exclude can drop this -- the directory denylist cannot.
printf 'var p=1,q=2,r=3,s=4,t=5,u=6,v=7,w=8,x=9,y=10;function m(){if(p==q){return r==s}return t==u}var n=m();console.log(n==v);\n' > "$FIX/client/public/jsdos/engine.min.js"

# Vendored minified file NOT named *.min.js (mirrors js-dos/js-dos.js exactly).
# Neither the directory denylist nor the *.min.js glob catches it -- only the
# looks-minified heuristic (a single >1000-char line) drops its lint findings.
python3 - "$FIX/client/public/jsdos/jsdos.js" <<'PYEOF'
import sys
# One ~3000-char minified line containing many == (each an eqeqeq violation).
line = "var z=0;" + "".join("if(a%d==b%d){z++}" % (i, i) for i in range(200)) + "\n"
with open(sys.argv[1], "w") as fh:
    fh.write(line)
PYEOF

# Gitignored local env file with a fake GitHub PAT (36 chars after ghp_).
printf 'GITHUB_TOKEN=ghp_FakeTokenForTesting1234567890abcdefX\n' > "$FIX/.env.local"

cat > "$FIX/.gitignore" <<'EOF'
dist/
.env.local
EOF

# Commit tracked content. dist/ and .env.local are gitignored (never committed);
# .audit/ is left untracked. The vendored engine.min.js is committed (tracked).
(
  cd "$FIX"
  git init -q
  git config user.email "test@example.com"
  git config user.name "test"
  git add src/real.js client/public/jsdos/engine.min.js client/public/jsdos/jsdos.js .gitignore
  git commit -q -m "fixture" --no-verify
) > /dev/null 2>&1

# ---------------------------------------------------------------------------
# Run the spine
# ---------------------------------------------------------------------------
printf '\nSpine-scope regression (issue #726): eslint,semgrep,gitleaks on fixture\n'

OUT="$TESTRUN_TMPDIR/out.jsonl"
set +e
bash "$SPINE_DIR/run.sh" \
  --repo "$FIX" \
  --tools "eslint,semgrep,gitleaks" \
  --output "$OUT" \
  2>/dev/null
RUN_EXIT=$?
set -e

if [[ $RUN_EXIT -eq 0 ]]; then
  pass "run.sh exits 0"
else
  fail "run.sh exits $RUN_EXIT (expected 0)"
fi

# ---------------------------------------------------------------------------
# Analyze findings with python (deterministic JSON parsing)
# ---------------------------------------------------------------------------
ANALYSIS="$(python3 - "$OUT" <<'PYEOF'
import json, sys

findings = []
with open(sys.argv[1]) as fh:
    for raw in fh:
        raw = raw.strip()
        if not raw:
            continue
        try:
            obj = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict) and "type" not in obj:
            findings.append(obj)

def path_of(f):
    return (f.get("location") or {}).get("path", "")

def is_excluded(p):
    if p.startswith(".audit/") or "/.audit/" in p:
        return True
    if p.startswith("dist/") or "/dist/" in p:
        return True
    if p.endswith(".min.js") or p.endswith(".min.css") or p.endswith(".bundle.js"):
        return True
    return False

excluded = [f for f in findings if is_excluded(path_of(f))]
leaked = [f for f in findings if f.get("check_id") == "secrets/leaked-credential"]
eqeqeq = [f for f in findings if f.get("check_id") == "lint/eqeqeq"]

nonreal = [f for f in findings if path_of(f) != "src/real.js"]

print("TOTAL=%d" % len(findings))
print("EXCLUDED=%d" % len(excluded))
print("LEAKED=%d" % len(leaked))
print("EQEQEQ=%d" % len(eqeqeq))
print("NONREAL=%d" % len(nonreal))
# real finding path
real_ok = any(path_of(f) == "src/real.js" for f in eqeqeq)
print("REAL_OK=%d" % (1 if real_ok else 0))
# Dump non-real / excluded / leaked paths for debugging
for f in nonreal:
    print("NONREAL_PATH=%s|%s" % (f.get("check_id", "?"), path_of(f)))
for f in leaked:
    print("LEAKED_PATH=%s" % path_of(f))
PYEOF
)"

get() { printf '%s\n' "$ANALYSIS" | grep "^$1=" | head -1 | cut -d= -f2; }

TOTAL="$(get TOTAL)"
EXCLUDED="$(get EXCLUDED)"
LEAKED="$(get LEAKED)"
REAL_OK="$(get REAL_OK)"

# Debug context on failure
print_debug() {
  printf '  --- analysis ---\n'
  printf '%s\n' "$ANALYSIS" | sed 's/^/    /'
}

# Assertion 1: no findings in generated/vendored/.audit paths
if [[ "$EXCLUDED" == "0" ]]; then
  pass "no findings under .audit/, dist/, public/vendor, or *.min.js"
else
  fail "found $EXCLUDED finding(s) in excluded paths (expected 0)"
  print_debug
fi

# Assertion 2: the real source finding is present
if [[ "$REAL_OK" == "1" ]]; then
  pass "real eqeqeq finding in src/real.js is reported"
else
  fail "real eqeqeq finding in src/real.js is missing"
  print_debug
fi

# Assertion 3: gitleaks does not report the gitignored .env.local as a leak
if [[ "$LEAKED" == "0" ]]; then
  pass "no gitleaks leaked-credential finding (gitignored .env.local not flagged)"
else
  fail "found $LEAKED leaked-credential finding(s) (expected 0; .env.local is gitignored)"
  print_debug
fi

# Assertion 4: exactly one finding total (the real source eqeqeq)
if [[ "$TOTAL" == "1" ]]; then
  pass "exactly one finding total"
else
  fail "found $TOTAL finding(s) total (expected exactly 1)"
  print_debug
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
