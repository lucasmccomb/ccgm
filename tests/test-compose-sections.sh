#!/usr/bin/env bash
set -uo pipefail

# Tests for lib/compose-sections.py (issue #1075): expand, idempotence,
# --check clean/drift, unknown section, unbalanced markers, multiple blocks.

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
COMPOSER="$REPO_ROOT/lib/compose-sections.py"
PASS=0
FAIL=0

ok()   { PASS=$((PASS + 1)); echo "  PASS: $1"; }
fail() { FAIL=$((FAIL + 1)); echo "  FAIL: $1"; }

expect_exit() { # name expected actual
  if [ "$3" -eq "$2" ]; then ok "$1"; else fail "$1 (expected exit $2, got $3)"; fi
}

new_root() {
  local r
  r="$(mktemp -d)"
  mkdir -p "$r/prompts/sections" "$r/modules/m/agents" "$r/modules/m/commands"
  printf 'Alpha line.\nSecond line.\n' > "$r/prompts/sections/alpha.md"
  printf 'Beta line.\n' > "$r/prompts/sections/beta.md"
  echo "$r"
}

# run <root> [args...]: prints the exit code; stderr lands in <root>/stderr.
run() {
  local root="$1"
  shift
  python3 "$COMPOSER" --root "$root" "$@" >/dev/null 2>"$root/stderr"
  echo $?
}

echo "=== compose-sections ==="

# expand
R="$(new_root)"
printf 'head\n<!-- ccgm:section alpha -->\nstale\n<!-- /ccgm:section alpha -->\ntail\n' > "$R/modules/m/agents/a.md"
expect_exit "expand exits 0" 0 "$(run "$R")"
EXPECT="$(printf 'head\n<!-- ccgm:section alpha -->\nAlpha line.\nSecond line.\n<!-- /ccgm:section alpha -->\ntail')"
if [ "$(cat "$R/modules/m/agents/a.md")" = "$EXPECT" ]; then
  ok "expand inlines section text between markers"
else
  fail "expand inlines section text between markers"
fi

# idempotence
cp "$R/modules/m/agents/a.md" "$R/before"
run "$R" >/dev/null
if cmp -s "$R/before" "$R/modules/m/agents/a.md"; then ok "second run changes nothing"; else fail "second run changes nothing"; fi

# --check clean
expect_exit "--check clean exits 0" 0 "$(run "$R" --check)"

# --check drift
printf 'head\n<!-- ccgm:section alpha -->\nedited by hand\n<!-- /ccgm:section alpha -->\n' > "$R/modules/m/agents/a.md"
expect_exit "--check on drift exits 1" 1 "$(run "$R" --check)"
if grep -q 'modules/m/agents/a.md' "$R/stderr" && grep -q 'alpha' "$R/stderr"; then
  ok "--check names file and block"
else
  fail "--check names file and block"
fi
if grep -q 'edited by hand' "$R/modules/m/agents/a.md"; then ok "--check does not rewrite"; else fail "--check does not rewrite"; fi
rm -rf "$R"

# unknown section
R="$(new_root)"
printf '<!-- ccgm:section nope -->\n<!-- /ccgm:section nope -->\n' > "$R/modules/m/commands/c.md"
expect_exit "unknown section exits 2" 2 "$(run "$R")"
expect_exit "unknown section exits 2 under --check" 2 "$(run "$R" --check)"
rm -rf "$R"

# unbalanced markers
R="$(new_root)"
printf '<!-- ccgm:section alpha -->\nno end\n' > "$R/modules/m/agents/a.md"
expect_exit "missing end marker exits 2" 2 "$(run "$R")"
printf 'stray\n<!-- /ccgm:section alpha -->\n' > "$R/modules/m/agents/a.md"
expect_exit "stray end marker exits 2" 2 "$(run "$R")"
printf '<!-- ccgm:section alpha -->\n<!-- /ccgm:section beta -->\n' > "$R/modules/m/agents/a.md"
expect_exit "mismatched end marker exits 2" 2 "$(run "$R")"
printf '<!-- ccgm:section alpha -->\n<!-- ccgm:section beta -->\n<!-- /ccgm:section beta -->\n<!-- /ccgm:section alpha -->\n' > "$R/modules/m/agents/a.md"
expect_exit "nested blocks exit 2" 2 "$(run "$R")"
rm -rf "$R"

# multiple blocks in one file; unmarked file untouched
R="$(new_root)"
printf '<!-- ccgm:section alpha -->\nx\n<!-- /ccgm:section alpha -->\nmid\n<!-- ccgm:section beta -->\n<!-- /ccgm:section beta -->\n' > "$R/modules/m/agents/a.md"
printf 'plain file\n' > "$R/modules/m/commands/plain.md"
run "$R" >/dev/null
EXPECT="$(printf '<!-- ccgm:section alpha -->\nAlpha line.\nSecond line.\n<!-- /ccgm:section alpha -->\nmid\n<!-- ccgm:section beta -->\nBeta line.\n<!-- /ccgm:section beta -->')"
if [ "$(cat "$R/modules/m/agents/a.md")" = "$EXPECT" ]; then ok "multiple blocks in one file expand"; else fail "multiple blocks in one file expand"; fi
if [ "$(cat "$R/modules/m/commands/plain.md")" = "plain file" ]; then ok "unmarked file untouched"; else fail "unmarked file untouched"; fi
rm -rf "$R"

echo ""
echo "Passed: $PASS  Failed: $FAIL"
[ "$FAIL" -eq 0 ]
