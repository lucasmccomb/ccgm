#!/usr/bin/env bash
# Unit test: modules/statusline/statusline.sh rendering.
#
# Pins the statusline-specific sections this module adds over the base script:
# multi-clone identity (.env.clone), session cost, and the compaction warning,
# plus the generic model parsing and graceful degradation on missing fields.
set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
STATUSLINE="$SCRIPT_DIR/../statusline.sh"

PASS=0
FAIL=0

TMPHOME="$(mktemp -d)"
trap 'rm -rf "$TMPHOME"' EXIT

# Render the full bar from a JSON payload with effort env stripped and a
# hermetic HOME, then strip ANSI so assertions match on plain text.
render() {  # $1 = stdin JSON, $2 = HOME dir
  printf '%s' "$1" \
    | env -u CLAUDE_CODE_EFFORT_LEVEL HOME="$2" bash "$STATUSLINE" \
    | sed 's/\x1b\[[0-9;]*m//g'
}

# First " | "-delimited field (model + effort).
model_field() {  # $1 = display_name
  local out
  out="$(render "$(printf '{"model":{"display_name":"%s"},"cwd":"%s"}' "$1" "$TMPHOME")" "$TMPHOME")"
  printf '%s' "${out%% | *}"
}

check_model() {  # $1 = display_name, $2 = expected model field
  local got; got="$(model_field "$1")"
  if [ "$got" = "$2" ]; then PASS=$((PASS+1)); echo "  PASS: model '$1' -> '$got'"
  else FAIL=$((FAIL+1)); echo "  FAIL: model '$1' -> got '$got', expected '$2'"; fi
}

contains() {  # $1 = label, $2 = haystack, $3 = needle
  case "$2" in
    *"$3"*) PASS=$((PASS+1)); echo "  PASS: $1 (found '$3')" ;;
    *)      FAIL=$((FAIL+1)); echo "  FAIL: $1 (missing '$3' in: $2)" ;;
  esac
}

absent() {  # $1 = label, $2 = haystack, $3 = needle
  case "$2" in
    *"$3"*) FAIL=$((FAIL+1)); echo "  FAIL: $1 (unexpected '$3' in: $2)" ;;
    *)      PASS=$((PASS+1)); echo "  PASS: $1 (no '$3')" ;;
  esac
}

echo "=== statusline: model parsing ==="
check_model "Opus 4.8 (1M context)" "🧠 O-4.8"
check_model "Sonnet 4.6"            "🐢 S-4.6"
check_model "Haiku 4.5"             "⚠️ H-4.5"
check_model "Opus 5"                "🧠 O-5"
check_model ""                      "$(basename "$TMPHOME")"

echo ""
echo "=== statusline: clone identity ==="
CLONE_DIR="$(mktemp -d)"
printf 'AGENT_ID=agent-2\n' > "$CLONE_DIR/.env.clone"
OUT="$(render "$(printf '{"model":{"display_name":"Opus 4.8"},"cwd":"%s"}' "$CLONE_DIR")" "$TMPHOME")"
contains "clone id rendered" "$OUT" "agent-2"
# No .env.clone -> no clone section.
OUT_NOCLONE="$(render "$(printf '{"model":{"display_name":"Opus 4.8"},"cwd":"%s"}' "$TMPHOME")" "$TMPHOME")"
absent "no clone id when no .env.clone" "$OUT_NOCLONE" "agent-"
rm -rf "$CLONE_DIR"

echo ""
echo "=== statusline: session cost ==="
OUT="$(render "$(printf '{"model":{"display_name":"Opus 4.8"},"cwd":"%s","cost":{"total_cost_usd":1.5}}' "$TMPHOME")" "$TMPHOME")"
contains "cost rendered" "$OUT" '$1.50'
# Missing cost -> no dollar section.
absent "no cost when field absent" "$(render "$(printf '{"model":{"display_name":"Opus 4.8"},"cwd":"%s"}' "$TMPHOME")" "$TMPHOME")" '$'

echo ""
echo "=== statusline: context vs auto-compact budget ==="
# 1M-context model: budget is capped at 500k, so 460k used = 92% (NOT 46% of 1M),
# which is the whole point — the bar reflects true pressure to auto-compaction.
OUT="$(render "$(printf '{"model":{"display_name":"Opus 4.8"},"cwd":"%s","context_window":{"total_input_tokens":460000,"context_window_size":1000000}}' "$TMPHOME")" "$TMPHOME")"
contains "1M model 460k -> 92%% of 500k budget" "$OUT" "ctx:92%"
contains "1M model 460k -> compact warning" "$OUT" "COMPACT SOON"
# 1M-context model at 250k -> 50% of budget, no warning.
OUT="$(render "$(printf '{"model":{"display_name":"Opus 4.8"},"cwd":"%s","context_window":{"total_input_tokens":250000,"context_window_size":1000000}}' "$TMPHOME")" "$TMPHOME")"
contains "1M model 250k -> 50%%" "$OUT" "ctx:50%"
absent "1M model 250k -> no warning" "$OUT" "COMPACT SOON"
# 200k model: budget == full window (min(200k,500k)); 180k = 90% -> warning.
OUT="$(render "$(printf '{"model":{"display_name":"Sonnet 4.6"},"cwd":"%s","context_window":{"total_input_tokens":180000,"context_window_size":200000}}' "$TMPHOME")" "$TMPHOME")"
contains "200k model 180k -> 90%%" "$OUT" "ctx:90%"
contains "200k model 180k -> compact warning" "$OUT" "COMPACT SOON"
# 200k model at 100k -> 50%, no warning.
absent "200k model 100k -> no warning" "$(render "$(printf '{"model":{"display_name":"Sonnet 4.6"},"cwd":"%s","context_window":{"total_input_tokens":100000,"context_window_size":200000}}' "$TMPHOME")" "$TMPHOME")" "COMPACT SOON"
# Over-budget clamps to 100%.
OUT="$(render "$(printf '{"model":{"display_name":"Opus 4.8"},"cwd":"%s","context_window":{"total_input_tokens":540000,"context_window_size":1000000}}' "$TMPHOME")" "$TMPHOME")"
contains "over-budget clamps to 100%%" "$OUT" "ctx:100%"
# Raw tokens take precedence over remaining_percentage (budget path, not fallback).
OUT="$(render "$(printf '{"model":{"display_name":"Opus 4.8"},"cwd":"%s","context_window":{"total_input_tokens":460000,"context_window_size":1000000,"remaining_percentage":54}}' "$TMPHOME")" "$TMPHOME")"
contains "raw tokens beat remaining_percentage" "$OUT" "ctx:92%"
absent "does not fall back to full-window 46%%" "$OUT" "ctx:46%"

echo ""
echo "=== statusline: compaction warning (fallback: remaining_percentage only) ==="
# Older Claude Code without raw token fields -> full-window %. 10% remaining fires.
OUT="$(render "$(printf '{"model":{"display_name":"Opus 4.8"},"cwd":"%s","context_window":{"remaining_percentage":10}}' "$TMPHOME")" "$TMPHOME")"
contains "compact warning at 10%% remaining" "$OUT" "COMPACT SOON"
contains "ctx shown at 90%% used" "$OUT" "ctx:90%"
# 50% remaining -> no warning.
absent "no compact warning at 50%% remaining" "$(render "$(printf '{"model":{"display_name":"Opus 4.8"},"cwd":"%s","context_window":{"remaining_percentage":50}}' "$TMPHOME")" "$TMPHOME")" "COMPACT SOON"

echo ""
echo "  Results: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]
