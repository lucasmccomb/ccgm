#!/usr/bin/env bash
# Unit test: lib/statusline.sh model rendering.
#
# Pins the generic family+version parsing. The point of these cases is that
# NEW model releases (4.9, 5.0, Sonnet 5, …) must render correctly with NO
# change to statusline.sh — if a future model ever needs a code edit here, one
# of the "future" assertions below will fail and tell us the parser regressed.
set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
STATUSLINE="$REPO_ROOT/lib/statusline.sh"

PASS=0
FAIL=0

TMPHOME="$(mktemp -d)"
trap 'rm -rf "$TMPHOME"' EXIT

# Render and return ONLY the model field. Hermetic: an empty HOME + cwd and a
# stripped effort env var mean no effort suffix, git branch, or settings noise —
# the output is just "<model> | <tmpdir>", so the model is everything before
# the first " | " separator.
model_field() {
  local out
  out="$(printf '{"model":{"display_name":"%s"},"cwd":"%s"}' "$1" "$TMPHOME" \
    | env -u CLAUDE_CODE_EFFORT_LEVEL HOME="$TMPHOME" bash "$STATUSLINE" \
    | sed 's/\x1b\[[0-9;]*m//g')"
  printf '%s' "${out%% | *}"
}

check() {  # $1 = display_name, $2 = expected model field
  local got
  got="$(model_field "$1")"
  if [ "$got" = "$2" ]; then
    PASS=$((PASS + 1))
    echo "  PASS: '$1' -> '$got'"
  else
    FAIL=$((FAIL + 1))
    echo "  FAIL: '$1' -> got '$got', expected '$2'"
  fi
}

echo "=== statusline model rendering ==="

# --- Current models (must match prior behavior exactly) ---
check "Opus 4.8 (1M context)" "🧠 O-4.8"
check "Opus 4.8"              "🧠 O-4.8"
check "Opus 4.7"              "🧠 O-4.7"
check "Opus 4.6"              "🧠 O-4.6"
check "Opus 4.5"              "O-4.5"
check "Opus 4"                "O-4"
check "Sonnet 4.6"            "🐢 S-4.6"
check "Sonnet 4.5"            "🐢 S-4.5"
check "Sonnet 4"              "🐢 S-4"
check "Haiku 4.5"             "⚠️ H-4.5"
check "Haiku"                 "⚠️ H"

# --- Future models: NO code edit should ever be needed for these ---
check "Opus 4.9"              "🧠 O-4.9"
check "Opus 4.10"             "🧠 O-4.10"
check "Opus 5"                "🧠 O-5"
check "Opus 5.2 (1M context)" "🧠 O-5.2"
check "Sonnet 5"             "🐢 S-5"
check "Sonnet 4.8"           "🐢 S-4.8"
check "Haiku 5"              "⚠️ H-5"

# --- Edges ---
check ""                      "$(basename "$TMPHOME")"   # no model -> dir is first field
check "Claude Gizmo 9"        "Gizmo"                    # unknown family -> sed fallback, plain

echo ""
echo "  Results: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]
