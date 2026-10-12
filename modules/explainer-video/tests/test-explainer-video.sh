#!/usr/bin/env bash
set -euo pipefail

# Content checks for the explainer-video module: the skill calls the render tool
# by absolute path in plain commands, and nothing in the module can open a
# window or play audio.

MODULE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SKILL="$MODULE_DIR/skills/explainer-video/SKILL.md"
TOOL="$MODULE_DIR/bin/ccgm-explainer-render"
FAILED=0

fail() {
  echo "FAIL: $1" >&2
  FAILED=1
}
ok() { echo "ok: $1"; }

[ -f "$SKILL" ] || fail "skills/explainer-video/SKILL.md is missing"
[ -x "$TOOL" ] || fail "bin/ccgm-explainer-render is missing or not executable"

if grep -q 'test -x "\$HOME/.claude/bin/ccgm-explainer-render"' "$SKILL" \
  && grep -q '^"\$HOME/.claude/bin/ccgm-explainer-render" ' "$SKILL"; then
  ok "skill checks the tool with test -x, then calls it by absolute path"
else
  fail "skill must run test -x and the tool as separate commands under \$HOME/.claude/bin"
fi

if grep -nE '\$\{[A-Za-z_]+:-' "$SKILL"; then
  fail "skill uses \${VAR:-default}; use plain \$HOME paths"
else
  ok "skill has no \${VAR:-default} expansions"
fi

# Strip comment-only lines, then look for anything that plays or previews.
if grep -vE '^[[:space:]]*#' "$TOOL" | grep -nE 'afplay|"-p"|--preview|"open"|webbrowser|ffplay|"-pql"|"-pqm"'; then
  fail "render tool contains a playback or preview call"
else
  ok "render tool has no playback or preview call"
fi

if grep -nE 'afplay|ffplay|manim .* -p( |$)' "$SKILL"; then
  fail "skill mentions a playback or preview command"
else
  ok "skill has no playback or preview command"
fi

if grep -q '"say", "-o"' "$TOOL"; then
  ok "say always writes to a file (-o)"
else
  fail "say must be called with -o"
fi

exit "$FAILED"
