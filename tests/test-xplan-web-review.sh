#!/usr/bin/env bash
# Smoke tests for modules/xplan/lib/xplan-web-review.py
# Verifies: headless fallback signal, error exit codes, endpoint behavior,
# path-traversal denial, and comments.json schema.
set -u

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
LIB="$REPO_ROOT/modules/xplan/lib/xplan-web-review.py"

PASS=0
FAIL=0

pass() { PASS=$((PASS + 1)); echo "  PASS: $1"; }
fail() { FAIL=$((FAIL + 1)); echo "  FAIL: $1"; }

echo "=== xplan-web-review smoke tests ==="

# -- Setup: scratch plan dir
TMPDIR=$(mktemp -d -t xplan-web-test-XXXXXX)
cleanup() {
  # Best-effort port cleanup; the script handles its own shutdown on submit
  [ -n "${SERVER_PID:-}" ] && kill "$SERVER_PID" 2>/dev/null
  # shellcheck disable=SC2317
  :
}
trap cleanup EXIT

cat > "$TMPDIR/plan.md" <<'EOF'
# Test Plan

## 1. Overview
Hello world.

## 2. Scope
### 2.1 v1
- Thing
EOF

cat > "$TMPDIR/research.md" <<'EOF'
# Research
## Finding
Data.
EOF

# -- Test 1: file exists and is executable
if [ -x "$LIB" ]; then
  pass "lib is executable: $LIB"
else
  fail "lib not executable or missing: $LIB"
  echo "FAIL: Results: $PASS passed, $FAIL failed"
  exit 1
fi

# -- Test 2: syntax valid
if python3 -c "import ast; ast.parse(open('$LIB').read())" 2>/dev/null; then
  pass "syntactically valid python"
else
  fail "syntax error in $LIB"
fi

# -- Test 3: XPLAN_NO_WEB=1 yields exit 1 (fallback signal)
XPLAN_NO_WEB=1 python3 "$LIB" "$TMPDIR" --no-open >/dev/null 2>&1
rc=$?
if [ "$rc" = "1" ]; then
  pass "XPLAN_NO_WEB=1 exits 1 (fallback signal)"
else
  fail "XPLAN_NO_WEB=1 exited $rc, expected 1"
fi

# -- Test 4: nonexistent dir yields exit 2
python3 "$LIB" "$TMPDIR/does-not-exist" --no-open >/dev/null 2>&1
rc=$?
if [ "$rc" = "2" ]; then
  pass "nonexistent plan dir exits 2"
else
  fail "nonexistent plan dir exited $rc, expected 2"
fi

# -- Test 5: dir without plan.md yields exit 2
EMPTY_DIR=$(mktemp -d -t xplan-empty-XXXXXX)
python3 "$LIB" "$EMPTY_DIR" --no-open >/dev/null 2>&1
rc=$?
if [ "$rc" = "2" ]; then
  pass "dir without plan.md exits 2"
else
  fail "dir without plan.md exited $rc, expected 2"
fi
rmdir "$EMPTY_DIR" 2>/dev/null

# -- Test 6: server starts, / returns 200 + HTML
PORT=47431
python3 "$LIB" "$TMPDIR" --no-open --port "$PORT" >/tmp/xplan-web-test-stdout.$$ 2>/tmp/xplan-web-test-stderr.$$ &
SERVER_PID=$!
sleep 0.8

code=$(curl -s -o /tmp/xplan-web-test-index.$$ -w "%{http_code}" "http://127.0.0.1:$PORT/")
if [ "$code" = "200" ] && grep -q "xplan review" /tmp/xplan-web-test-index.$$; then
  pass "GET / returns 200 and expected HTML"
else
  fail "GET / returned $code (expected 200)"
fi

# -- Test 7: /raw/plan.md returns markdown
code=$(curl -s -o /tmp/xplan-web-test-md.$$ -w "%{http_code}" "http://127.0.0.1:$PORT/raw/plan.md")
if [ "$code" = "200" ] && grep -q "# Test Plan" /tmp/xplan-web-test-md.$$; then
  pass "GET /raw/plan.md returns the markdown"
else
  fail "GET /raw/plan.md returned $code or wrong content"
fi

# -- Test 8: /raw/research.md also works
code=$(curl -s -o /dev/null -w "%{http_code}" "http://127.0.0.1:$PORT/raw/research.md")
if [ "$code" = "200" ]; then
  pass "GET /raw/research.md returns 200"
else
  fail "GET /raw/research.md returned $code"
fi

# -- Test 9: path traversal denied
code=$(curl -s -o /dev/null -w "%{http_code}" "http://127.0.0.1:$PORT/raw/../../etc/passwd")
if [ "$code" = "404" ]; then
  pass "path traversal ../../etc/passwd denied (404)"
else
  fail "path traversal returned $code, expected 404"
fi

# -- Test 10: non-markdown file denied
echo "secret" > "$TMPDIR/secret.txt"
code=$(curl -s -o /dev/null -w "%{http_code}" "http://127.0.0.1:$PORT/raw/secret.txt")
if [ "$code" = "404" ]; then
  pass "non-.md file denied (404)"
else
  fail "non-.md file returned $code, expected 404"
fi
rm "$TMPDIR/secret.txt" 2>/dev/null

# -- Test 11: POST /submit writes comments.json and shuts down
curl -s -X POST -H 'Content-Type: application/json' \
  -d '{"action":"deepen","comments":[{"anchor":"plan.md::2. Scope","file":"plan.md","section_title":"2. Scope","text":"expand this","ts":"2026-04-24T10:00:00Z","status":"pending"}]}' \
  "http://127.0.0.1:$PORT/submit" >/dev/null

# Give the server ~1s to write and shut down
wait "$SERVER_PID" 2>/dev/null
SERVER_PID=""

if [ -f "$TMPDIR/comments.json" ]; then
  pass "POST /submit wrote comments.json"
else
  fail "comments.json not created after /submit"
fi

if python3 -c "
import json, sys
d = json.load(open('$TMPDIR/comments.json'))
assert d['action'] == 'deepen', 'action != deepen'
assert len(d['comments']) == 1, 'wrong comment count'
assert d['comments'][0]['text'] == 'expand this', 'wrong comment text'
assert d['comments'][0]['section_title'] == '2. Scope', 'wrong section title'
" 2>/tmp/xplan-web-test-assert.$$; then
  pass "comments.json has correct schema and payload"
else
  fail "comments.json schema mismatch: $(cat /tmp/xplan-web-test-assert.$$)"
fi

# -- Test 12: POST /accept on a second server writes action=accept
rm "$TMPDIR/comments.json" 2>/dev/null
PORT=47432
python3 "$LIB" "$TMPDIR" --no-open --port "$PORT" >/dev/null 2>&1 &
SERVER_PID=$!
sleep 0.8

curl -s -X POST -H 'Content-Type: application/json' \
  -d '{"action":"accept","comments":[]}' \
  "http://127.0.0.1:$PORT/accept" >/dev/null

wait "$SERVER_PID" 2>/dev/null
SERVER_PID=""

if python3 -c "
import json
d = json.load(open('$TMPDIR/comments.json'))
assert d['action'] == 'accept', 'action != accept'
assert d['comments'] == [], 'comments not empty on accept'
" 2>/dev/null; then
  pass "POST /accept writes action=accept with empty comments"
else
  fail "/accept did not write expected payload"
fi

# -- Cleanup scratch files
rm -f /tmp/xplan-web-test-stdout.$$ /tmp/xplan-web-test-stderr.$$ \
      /tmp/xplan-web-test-index.$$ /tmp/xplan-web-test-md.$$ \
      /tmp/xplan-web-test-assert.$$

# Scratch plan dir: best-effort, files only
rm -f "$TMPDIR/plan.md" "$TMPDIR/research.md" "$TMPDIR/comments.json"
rmdir "$TMPDIR" 2>/dev/null

echo ""
echo "==================================="
echo "  Results: $PASS passed, $FAIL failed"
echo "==================================="

if [ "$FAIL" -gt 0 ]; then
  exit 1
fi
exit 0
