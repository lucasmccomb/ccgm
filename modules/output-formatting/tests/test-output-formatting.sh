#!/usr/bin/env bash
set -euo pipefail

# Content checks for the output-formatting module: the always-loaded rule stays
# small and scoped, /explain names every rung, and callers resolve ccgm-md-page
# by absolute path with a missing-file note.

MODULE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RULE="$MODULE_DIR/rules/output-medium.md"
EXPLAIN="$MODULE_DIR/commands/explain.md"
SKILL="$MODULE_DIR/skills/output-medium/SKILL.md"
FAILED=0

fail() {
  echo "FAIL: $1" >&2
  FAILED=1
}
ok() { echo "ok: $1"; }

# --- rule: line budget and scope line ---------------------------------------
if [ ! -f "$RULE" ]; then
  fail "rules/output-medium.md is missing"
else
  LINES="$(wc -l < "$RULE" | tr -d ' ')"
  if [ "$LINES" -le 20 ]; then ok "rule is $LINES lines (budget 20)"; else fail "rule is $LINES lines, budget is 20"; fi
  if head -n 1 "$RULE" | grep -q "^# " && sed -n 3p "$RULE" | grep -q "^Applies to text addressed to the operator"; then
    ok "rule has a heading on line 1 and the operator scope sentence directly under it"
  else
    fail "rule needs a '# ' heading on line 1 and 'Applies to text addressed to the operator' on line 3"
  fi
  if grep -q "output-medium" "$RULE" && grep -qi "skill" "$RULE"; then
    ok "rule points at the output-medium skill"
  else
    fail "rule must tell the agent to load the output-medium skill"
  fi
fi

# --- /explain: all four rungs and the video fallback ------------------------
if [ ! -f "$EXPLAIN" ]; then
  fail "commands/explain.md is missing"
else
  for rung in prose diagram page video; do
    if grep -qi "$rung" "$EXPLAIN"; then ok "explain.md names the $rung rung"; else fail "explain.md does not name the $rung rung"; fi
  done
  if grep -qi "explainer-video" "$EXPLAIN" && grep -qi "offer" "$EXPLAIN"; then
    ok "explain.md covers the missing explainer-video fallback"
  else
    fail "explain.md must say what happens when 'as video' runs without explainer-video"
  fi
fi

# --- callers use the absolute path and survive a missing tool ---------------
for f in "$SKILL" "$EXPLAIN"; do
  [ -f "$f" ] || { fail "$f is missing"; continue; }
  # Guard-safe form: a separate test -x, then the plain absolute call. No ${VAR:-default}.
  if grep -q 'test -x "\$HOME/.claude/bin/ccgm-md-page"' "$f" && grep -q '"\$HOME/.claude/bin/ccgm-md-page" ' "$f"; then
    ok "$(basename "$f") checks with test -x, then calls ccgm-md-page by absolute path"
  else
    fail "$f must use 'test -x \"\$HOME/.claude/bin/ccgm-md-page\"' then '\"\$HOME/.claude/bin/ccgm-md-page\" ...'"
  fi
  if grep -q 'CCGM_BIN' "$f"; then fail "$f still references CCGM_BIN"; else ok "$(basename "$f") has no CCGM_BIN default"; fi
  if grep -qi "missing" "$f"; then ok "$(basename "$f") handles a missing ccgm-md-page"; else fail "$f must say what to do when ccgm-md-page is missing"; fi
done

# --- diagram width check runs through the linter and is reported -------------
for f in "$SKILL" "$EXPLAIN"; do
  if grep -q 'python3 -c' "$f"; then fail "$(basename "$f") still mentions python3 -c"; else ok "$(basename "$f") has no python3 -c"; fi
  if grep -q 'test -x "\$HOME/.claude/bin/ccgm-prose-lint"' "$f" && grep -q '"\$HOME/.claude/bin/ccgm-prose-lint" --strict' "$f" && grep -q 'diagram-width' "$f"; then
    ok "$(basename "$f") checks diagram width with ccgm-prose-lint"
  else
    fail "$f must check width with test -x, then ccgm-prose-lint --strict, and name diagram-width"
  fi
done
if grep -q 'Check: ' "$EXPLAIN"; then ok "explain.md ends with a Check: line"; else fail "explain.md must end its summary with a 'Check:' line"; fi

if [ "$FAILED" = "0" ]; then
  echo "test-output-formatting.sh: PASS"
else
  exit 1
fi
