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
  if grep -q '\${CCGM_BIN:-\$HOME/.claude/bin}/ccgm-md-page' "$f"; then
    ok "$(basename "$(dirname "$f")")/$(basename "$f") calls ccgm-md-page by absolute path"
  else
    fail "$f must call \"\${CCGM_BIN:-\$HOME/.claude/bin}/ccgm-md-page\""
  fi
  if grep -qi "missing" "$f"; then ok "$(basename "$f") handles a missing ccgm-md-page"; else fail "$f must say what to do when ccgm-md-page is missing"; fi
done

if [ "$FAILED" = "0" ]; then
  echo "test-output-formatting.sh: PASS"
else
  exit 1
fi
