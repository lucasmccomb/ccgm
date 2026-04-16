#!/bin/bash
# Polls ccusage for 5hr block usage. Writes ~/.claude/halt.flag at THRESHOLD%.
# Clears flag on block reset and sends a "resumed" notification.

set -euo pipefail

THRESHOLD="${HALT_THRESHOLD:-99}"
FLAG="$HOME/.claude/halt.flag"
LOG="$HOME/.claude/halt.log"
CCUSAGE="$(command -v ccusage || true)"

if [ -z "$CCUSAGE" ]; then
  # Fall back to npx; monitor runs every minute so install latency isn't fatal
  CCUSAGE="npx -y ccusage@latest"
fi

notify() {
  local title="$1" msg="$2"
  osascript -e "display notification \"$msg\" with title \"$title\" sound name \"Submarine\"" 2>/dev/null || true
  echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) $title :: $msg" >> "$LOG"
}

json="$($CCUSAGE blocks --active --json --token-limit max 2>/dev/null || echo '{"blocks":[]}')"

read -r is_active percent end_time <<<"$(
  echo "$json" | jq -r '
    .blocks[0] // {} |
    [(.isActive // false), (.tokenLimitStatus.percentUsed // 0), (.endTime // "")] |
    @tsv'
)"

# No active block -> clear any stale flag
if [ "$is_active" != "true" ]; then
  if [ -f "$FLAG" ]; then
    rm -f "$FLAG"
    notify "Claude usage: resumed" "5hr block reset — agents unblocked"
  fi
  exit 0
fi

# Flag exists but block rolled over -> clear it
if [ -f "$FLAG" ]; then
  flag_end="$(grep '^reset_iso=' "$FLAG" | cut -d= -f2- || echo '')"
  if [ "$flag_end" != "$end_time" ]; then
    rm -f "$FLAG"
    notify "Claude usage: resumed" "5hr block reset — agents unblocked"
  fi
fi

# Compare percent as float via awk (jq gives a float)
over_threshold="$(awk -v p="$percent" -v t="$THRESHOLD" 'BEGIN{print (p+0 >= t+0) ? 1 : 0}')"

if [ "$over_threshold" = "1" ] && [ ! -f "$FLAG" ]; then
  cat > "$FLAG" <<EOF
reset_iso=$end_time
percent=$(printf '%.1f' "$percent")
triggered_at=$(date -u +%Y-%m-%dT%H:%M:%SZ)
EOF
  pretty_end="$(date -j -f '%Y-%m-%dT%H:%M:%S' "${end_time%.*}" '+%-I:%M %p' 2>/dev/null || echo "$end_time")"
  notify "Claude usage: HALTED" "5hr block at $(printf '%.1f' "$percent")% — resumes $pretty_end"
fi
