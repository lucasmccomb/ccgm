#!/usr/bin/env bash
# Checks that the four reviewer-facing surfaces carry the prose lint gate, that
# pr-description states its diagram trigger, and that the linter rejects a
# long descriptive sentence under --strict.
# Override the linter path with PROSE_LINT=/path/to/ccgm-prose-lint.

set -u
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
PROSE_LINT="${PROSE_LINT:-$ROOT/modules/writing-system/bin/ccgm-prose-lint}"
FAILS=0

fail() { echo "FAIL: $1"; FAILS=$((FAILS + 1)); }
pass() { echo "PASS: $1"; }

FILES=(
  modules/commands-core/skills/pr-description/SKILL.md
  modules/commands-core/commands/ghi.md
  modules/multi-agent/commands/handoff.md
  modules/session-lifecycle/commands/sds.md
)

for f in "${FILES[@]}"; do
  p="$ROOT/$f"
  if [ ! -f "$p" ]; then fail "$f missing"; continue; fi
  if grep -qF '"$HOME/.claude/bin/ccgm-prose-lint" --strict' "$p"; then
    pass "$f calls the linter with --strict"
  else
    fail "$f lacks the linter call (absolute-path form with --strict)"
  fi
  if grep -qF 'test -x "$HOME/.claude/bin/ccgm-prose-lint"' "$p"; then
    pass "$f checks the linter exists with test -x"
  else
    fail "$f lacks the test -x line"
  fi
  if grep -qF 'CCGM_BIN' "$p"; then
    fail "$f still uses CCGM_BIN (guard cannot resolve it)"
  fi
  if grep -qF 'ccgm-prose-lint not installed; skipping the prose check' "$p"; then
    pass "$f has the skip note"
  else
    fail "$f lacks the skip note"
  fi
done

SKILL="$ROOT/modules/commands-core/skills/pr-description/SKILL.md"
if grep -qF '### How it fits' "$SKILL" \
  && grep -qF '3 or more files' "$SKILL" \
  && grep -qF 'at most 12 nodes' "$SKILL" \
  && grep -qF '@mermaid-js/mermaid-cli' "$SKILL" \
  && grep -qF -- '- Diagram:' "$SKILL"; then
  pass "pr-description states the diagram trigger"
else
  fail "pr-description lacks the diagram trigger text"
fi

for f in modules/multi-agent/commands/handoff.md modules/session-lifecycle/commands/sds.md; do
  if grep -qF 'never the kickoff prompt' "$ROOT/$f"; then
    pass "$f exempts the kickoff prompt"
  else
    fail "$f does not exempt the kickoff prompt"
  fi
done

# Linter behavior on a fixture with a 30-word descriptive sentence.
if [ ! -f "$PROSE_LINT" ]; then
  fail "linter not found at $PROSE_LINT (rebase on main after the writing-system linter merges, or set PROSE_LINT)"
else
  FIX="$(mktemp)"
  trap 'rm -f "$FIX"' EXIT
  cat > "$FIX" <<'BODY'
This change updates the way that the installer reads the configuration files from the home directory so that every module can find the settings it needs when the user runs it twice.
BODY
  python3 "$PROSE_LINT" --strict "$FIX" >/dev/null 2>&1
  rc=$?
  if [ "$rc" -eq 1 ]; then
    pass "linter exits 1 under --strict on a 30-word sentence"
  else
    fail "linter exit was $rc, expected 1"
  fi
fi

echo
if [ "$FAILS" -eq 0 ]; then echo "All prose gate tests passed"; exit 0; fi
echo "$FAILS test(s) failed"
exit 1
