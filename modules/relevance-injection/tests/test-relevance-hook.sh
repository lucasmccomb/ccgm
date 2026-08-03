#!/usr/bin/env bash
#
# test-relevance-hook.sh — verify the SessionStart hook is a strict no-op
# unless the opt-in flag is set, and emits the safety core when enabled.
#
# Property (a) at the hook level: default (no flag) => zero output, behavior
# unchanged. Properties (c)/(d) reinforced: when enabled, the safety core is
# always present in the emitted pointer.
#
# Portable: bash 3.2, no GNU-only flags. Builds a fake HOME so the test never
# touches the developer's real ~/.claude.

set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MODULE_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
REPO_ROOT="$(cd "$MODULE_DIR/../.." && pwd)"
HOOK="$MODULE_DIR/hooks/relevance-inject.py"

PASS=0
FAIL=0
pass() { PASS=$((PASS + 1)); echo "  PASS: $1"; }
fail() { FAIL=$((FAIL + 1)); echo "  FAIL: $1"; }

FAKE_HOME="$(mktemp -d)"
trap 'rm -rf "$FAKE_HOME"' EXIT

mkdir -p "$FAKE_HOME/.claude/lib"
# Make the selection library importable at the installed location.
cp "$MODULE_DIR/lib/relevance_select.py" "$FAKE_HOME/.claude/lib/"

# A manifest that points ccgmRoot at the real repo (so module.json files load)
# and lists a small installed set including safety-core + a scoped module.
cat > "$FAKE_HOME/.claude/.ccgm-manifest.json" <<EOF
{
  "version": "1.0.0",
  "ccgmRoot": "$REPO_ROOT",
  "modules": ["git-workflow", "verification", "tailwind", "code-quality"]
}
EOF

STARTUP_INPUT='{"source":"startup"}'

# --- Test 1: no flag, no .ccgm.env => no-op (empty output) ---
out=$(printf '%s' "$STARTUP_INPUT" | HOME="$FAKE_HOME" python3 "$HOOK" 2>/dev/null)
if [ -z "$out" ]; then
  pass "no .ccgm.env => hook emits nothing (default behavior unchanged)"
else
  fail "expected empty output with no flag, got: $out"
fi

# --- Test 2: flag explicitly false => still no-op ---
cat > "$FAKE_HOME/.claude/.ccgm.env" <<'EOF'
CCGM_RELEVANCE_INJECTION=false
EOF
out=$(printf '%s' "$STARTUP_INPUT" | HOME="$FAKE_HOME" python3 "$HOOK" 2>/dev/null)
if [ -z "$out" ]; then
  pass "flag=false => hook emits nothing"
else
  fail "expected empty output with flag=false, got: $out"
fi

# --- Test 3: flag true => emits pointer including the safety core ---
cat > "$FAKE_HOME/.claude/.ccgm.env" <<'EOF'
CCGM_RELEVANCE_INJECTION=true
CCGM_RELEVANCE_LANGS=css
CCGM_RELEVANCE_TASKTYPES=frontend
EOF
out=$(printf '%s' "$STARTUP_INPUT" | HOME="$FAKE_HOME" python3 "$HOOK" 2>/dev/null)
if printf '%s' "$out" | grep -q "ccgm-relevance-injection"; then
  pass "flag=true => emits relevance-injection block"
else
  fail "expected relevance-injection block, got: $out"
fi
# Safety core (git-workflow, verification) must be present regardless of profile.
if printf '%s' "$out" | grep -q "git-workflow" && printf '%s' "$out" | grep -q "verification"; then
  pass "flag=true => safety core present in output"
else
  fail "expected safety core in output, got: $out"
fi
# Profile-matched situational module (tailwind: css/frontend) present.
if printf '%s' "$out" | grep -q "tailwind"; then
  pass "flag=true => profile-matched module (tailwind) present"
else
  fail "expected tailwind in output, got: $out"
fi

# --- Test 4: non-startup source => no-op even with flag on ---
out=$(printf '%s' '{"source":"resume"}' | HOME="$FAKE_HOME" python3 "$HOOK" 2>/dev/null)
if [ -z "$out" ]; then
  pass "source=resume => no-op even with flag on"
else
  fail "expected no-op on resume, got: $out"
fi

# --- Test 5: flag on but no manifest => no-op (cannot select, fail safe) ---
rm -f "$FAKE_HOME/.claude/.ccgm-manifest.json"
out=$(printf '%s' "$STARTUP_INPUT" | HOME="$FAKE_HOME" python3 "$HOOK" 2>/dev/null)
if [ -z "$out" ]; then
  pass "flag on but no manifest => no-op"
else
  fail "expected no-op without manifest, got: $out"
fi

echo ""
echo "test-relevance-hook.sh: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]
