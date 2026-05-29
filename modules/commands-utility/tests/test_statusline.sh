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

# --- Effort + ultracode label ---
# Pass effort explicitly; the model field carries the effort suffix
# ("🧠 O-4.8 Max"). The first " | "-delimited field is model + effort.
field_first() {  # $1 = full stdin JSON, $2 = HOME dir
  printf '%s' "$1" \
    | env -u CLAUDE_CODE_EFFORT_LEVEL HOME="$2" bash "$STATUSLINE" \
    | sed 's/\x1b\[[0-9;]*m//g' \
    | sed 's/ | .*//'
}
check_effort() {  # $1 = label, $2 = stdin JSON, $3 = HOME, $4 = expected
  local got
  got="$(field_first "$2" "$3")"
  if [ "$got" = "$4" ]; then
    PASS=$((PASS + 1)); echo "  PASS: $1 -> '$got'"
  else
    FAIL=$((FAIL + 1)); echo "  FAIL: $1 -> got '$got', expected '$4'"
  fi
}

echo ""
echo "=== effort + ultracode ==="
M='{"model":{"display_name":"Opus 4.8"},"cwd":"'"$TMPHOME"'"'
# Baseline effort labels (no ultracode) — must be unchanged.
check_effort "max"               "$M,\"effort\":{\"level\":\"max\"}}"                     "$TMPHOME" "🧠 O-4.8 Max"
check_effort "xhigh"             "$M,\"effort\":{\"level\":\"xhigh\"}}"                   "$TMPHOME" "🧠 O-4.8 XH"
# Ultracode keeps the accurate effort (always xhigh -> XH) and bookends with ✨.
# Via stdin .effort.level=="ultracode" (defensive: no effort case -> forced XH).
check_effort "effort=ultracode"  "$M,\"effort\":{\"level\":\"ultracode\"}}"               "$TMPHOME" "🧠 O-4.8 ✨XH✨"
# Via a stdin boolean (defensive: auto-works if CC adds the flag).
check_effort "stdin .ultracode"  "$M,\"effort\":{\"level\":\"xhigh\"},\"ultracode\":true}" "$TMPHOME" "🧠 O-4.8 ✨XH✨"
# Ultracode forces XH even if stdin claims another level (ultracode IS xhigh).
check_effort "ultracode forces XH" "$M,\"effort\":{\"level\":\"max\"},\"ultracode\":true}" "$TMPHOME" "🧠 O-4.8 ✨XH✨"

# Ultracode via the `ultracode` settings key — the channel that works today.
UCHOME="$(mktemp -d)"
mkdir -p "$UCHOME/.claude"
printf '{"ultracode": true}' > "$UCHOME/.claude/settings.json"
# CC resolves effort to xhigh under ultracode, so stdin reports xhigh here.
check_effort "settings ultracode" "{\"model\":{\"display_name\":\"Opus 4.8\"},\"cwd\":\"$UCHOME\",\"effort\":{\"level\":\"xhigh\"}}" "$UCHOME" "🧠 O-4.8 ✨XH✨"
# Settings flag with NO stdin effort -> still ✨XH✨ (forced from the ultracode flag).
check_effort "settings ultracode, no stdin effort" "{\"model\":{\"display_name\":\"Opus 4.8\"},\"cwd\":\"$UCHOME\"}" "$UCHOME" "🧠 O-4.8 ✨XH✨"
rm -rf "$UCHOME"

echo ""
echo "  Results: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]
