#!/usr/bin/env bash
# Claude Code status line script
# Displays: model | directory branch | context usage | 5h & 7d rate limits

input=$(cat)

# --- Model (abbreviated: O-4.6, S-4.6, H-4.5, etc.) with tier indicators
model_raw=$(echo "$input" | jq -r '.model.display_name // ""')
case "$model_raw" in
  *"Opus 4.7"*)   model_abbr="O-4.7"; model_tier="opus-best" ;;
  *"Opus 4.6"*)   model_abbr="O-4.6"; model_tier="opus-best" ;;
  *"Opus 4.5"*)   model_abbr="O-4.5"; model_tier="opus-other" ;;
  *"Opus 4"*)     model_abbr="O-4"; model_tier="opus-other" ;;
  *"Sonnet 4.6"*) model_abbr="S-4.6"; model_tier="sonnet" ;;
  *"Sonnet 4.5"*) model_abbr="S-4.5"; model_tier="sonnet" ;;
  *"Sonnet 4"*)   model_abbr="S-4"; model_tier="sonnet" ;;
  *"Haiku 4.5"*)  model_abbr="H-4.5"; model_tier="haiku" ;;
  *"Haiku"*)      model_abbr="H"; model_tier="haiku" ;;
  "")             model_abbr=""; model_tier="" ;;
  *)              model_abbr=$(echo "$model_raw" | sed 's/Claude //;s/ .*//'); model_tier="unknown" ;;
esac

# --- Directory: immediate dir name only
cwd=$(echo "$input" | jq -r '.cwd // ""')
cwd_display="${cwd##*/}"

# --- Effort level (env > project local > project > user settings)
# Statusline stdin does not expose effort, so read the same sources Claude Code uses.
# /effort max is session-only unless set via CLAUDE_CODE_EFFORT_LEVEL, so the
# displayed value reflects the last persisted setting when max is a live override.
read_effort_from() {
  [ -f "$1" ] || return 1
  jq -r '.effortLevel // empty' "$1" 2>/dev/null
}
effort_raw="${CLAUDE_CODE_EFFORT_LEVEL:-}"
if [ -z "$effort_raw" ] && [ -n "$cwd" ]; then
  effort_raw=$(read_effort_from "$cwd/.claude/settings.local.json")
  [ -z "$effort_raw" ] && effort_raw=$(read_effort_from "$cwd/.claude/settings.json")
fi
[ -z "$effort_raw" ] && effort_raw=$(read_effort_from "$HOME/.claude/settings.json")
case "$effort_raw" in
  low)    effort_abbr="L" ;;
  medium) effort_abbr="M" ;;
  high)   effort_abbr="H" ;;
  xhigh)  effort_abbr="XH" ;;
  max)    effort_abbr="Max" ;;
  *)      effort_abbr="" ;;
esac

# --- Git branch (skip optional locks to avoid hangs in multi-clone repos)
git_branch=""
if [ -d "$cwd/.git" ] || git -C "$cwd" rev-parse --git-dir >/dev/null 2>&1; then
  git_branch=$(git -C "$cwd" -c core.fsmonitor=false symbolic-ref --short HEAD 2>/dev/null \
    || git -C "$cwd" -c core.fsmonitor=false rev-parse --short HEAD 2>/dev/null)
fi

# --- Context used (inverted from remaining)
remaining=$(echo "$input" | jq -r '.context_window.remaining_percentage // empty')

# --- Rate limits (5h session + 7-day)
five_hour=$(echo "$input" | jq -r '.rate_limits.five_hour.used_percentage // empty')
five_hour_resets=$(echo "$input" | jq -r '.rate_limits.five_hour.resets_at // empty')
weekly=$(echo "$input" | jq -r '.rate_limits.seven_day.used_percentage // empty')
weekly_resets=$(echo "$input" | jq -r '.rate_limits.seven_day.resets_at // empty')

# --- ANSI color codes
RESET='\033[0m'
CYAN='\033[36m'
YELLOW='\033[33m'
GREEN='\033[32m'
RED='\033[31m'
DIM='\033[2m'
BLUE='\033[34m'
ORANGE='\033[38;5;208m'

# Compact usage bar: 5 chars wide
make_bar() {
  local pct=$1 color=$2
  local bar_len=5
  local filled=$(( (pct * bar_len + 50) / 100 ))
  [ "$filled" -gt "$bar_len" ] && filled=$bar_len
  [ "$filled" -lt 0 ] && filled=0
  local empty=$(( bar_len - filled ))
  local bar=""
  for ((i=0; i<filled; i++)); do bar="${bar}█"; done
  local empty_part=""
  for ((i=0; i<empty; i++)); do empty_part="${empty_part}░"; done
  printf "${color}%s${DIM}%s${RESET}" "$bar" "$empty_part"
}

SEP=$(printf " ${DIM}|${RESET} ")
sections=()

# Model with tier indicators + optional effort suffix
if [ -n "$model_abbr" ]; then
  effort_suffix=""
  [ -n "$effort_abbr" ] && effort_suffix="$(printf " ${DIM}%s${RESET}" "$effort_abbr")"
  case "$model_tier" in
    opus-best)
      sections+=("$(printf "${BLUE}🧠 %s${RESET}%s" "$model_abbr" "$effort_suffix")")
      ;;
    sonnet)
      sections+=("$(printf "${ORANGE}🐢 %s${RESET}%s" "$model_abbr" "$effort_suffix")")
      ;;
    haiku)
      sections+=("$(printf "${RED}⚠️ %s${RESET}%s" "$model_abbr" "$effort_suffix")")
      ;;
    *)
      sections+=("$(printf "%s%s" "$model_abbr" "$effort_suffix")")
      ;;
  esac
fi

# Dir + git branch (combined)
dir_part="$(printf "${CYAN}%s${RESET}" "$cwd_display")"
if [ -n "$git_branch" ]; then
  dir_part="${dir_part} $(printf "${YELLOW}%s${RESET}" "$git_branch")"
fi
sections+=("$dir_part")

# Context used (100 - remaining)
if [ -n "$remaining" ]; then
  remaining_int=$(printf '%.0f' "$remaining")
  used_int=$((100 - remaining_int))
  if [ "$used_int" -lt 60 ]; then
    ctx_color="$GREEN"
  elif [ "$used_int" -lt 85 ]; then
    ctx_color="$YELLOW"
  else
    ctx_color="$RED"
  fi
  sections+=("$(printf "${ctx_color}ctx:${used_int}%%${RESET}")")
fi

# 5-hour rate limit with bar and reset countdown
if [ -n "$five_hour" ]; then
  five_int=$(printf '%.0f' "$five_hour")
  if [ "$five_int" -lt 60 ]; then
    rl_color="$GREEN"
  elif [ "$five_int" -lt 85 ]; then
    rl_color="$YELLOW"
  else
    rl_color="$RED"
  fi
  five_part="$(printf "${rl_color}5h:${five_int}%%${RESET} ")$(make_bar "$five_int" "$rl_color")"
  if [ -n "$five_hour_resets" ]; then
    now=$(date +%s)
    diff=$(( five_hour_resets - now ))
    if [ "$diff" -gt 0 ]; then
      hours=$(( diff / 3600 ))
      mins=$(( (diff % 3600) / 60 ))
      if [ "$hours" -gt 0 ]; then
        five_part="${five_part} $(printf "${DIM}${hours}h${mins}m${RESET}")"
      else
        five_part="${five_part} $(printf "${DIM}${mins}m${RESET}")"
      fi
    fi
  fi
  sections+=("$five_part")
fi

# 7-day rate limit with bar and reset countdown
if [ -n "$weekly" ]; then
  weekly_int=$(printf '%.0f' "$weekly")
  if [ "$weekly_int" -lt 60 ]; then
    wk_color="$GREEN"
  elif [ "$weekly_int" -lt 85 ]; then
    wk_color="$YELLOW"
  else
    wk_color="$RED"
  fi
  wk_part="$(printf "${wk_color}7d:${weekly_int}%%${RESET} ")$(make_bar "$weekly_int" "$wk_color")"
  if [ -n "$weekly_resets" ]; then
    now=$(date +%s)
    diff=$(( weekly_resets - now ))
    if [ "$diff" -gt 0 ]; then
      days=$(( diff / 86400 ))
      hours=$(( (diff % 86400) / 3600 ))
      if [ "$days" -gt 0 ]; then
        wk_part="${wk_part} $(printf "${DIM}${days}d${hours}h${RESET}")"
      else
        mins=$(( (diff % 3600) / 60 ))
        wk_part="${wk_part} $(printf "${DIM}${hours}h${mins}m${RESET}")"
      fi
    fi
  fi
  sections+=("$wk_part")
fi

# Join sections with pipe separator
output=""
for i in "${!sections[@]}"; do
  if [ "$i" -gt 0 ]; then
    output="${output}${SEP}"
  fi
  output="${output}${sections[$i]}"
done

printf "%s" "$output"
