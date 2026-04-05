#!/usr/bin/env bash
# Claude Code status line script
# Displays: model | session | directory branch | LOC | context usage | cost | 5h & 7d rate limits

input=$(cat)

# --- Session ID (first 8 chars) and session name
session_id=$(echo "$input" | jq -r '.session_id // ""')
session_name=$(echo "$input" | jq -r '.session_name // ""')
session_id_short="${session_id:0:8}"

# --- LOC tracking
lines_added=$(echo "$input" | jq -r '.cost.total_lines_added // 0')
lines_removed=$(echo "$input" | jq -r '.cost.total_lines_removed // 0')

# --- Cost tracking
total_cost=$(echo "$input" | jq -r '.cost.total_cost_usd // 0')

# --- Model (abbreviated: O-4.6, S-4.6, H-4.5, etc.) with tier indicators
model_raw=$(echo "$input" | jq -r '.model.display_name // ""')
case "$model_raw" in
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

# Model with tier indicators
if [ -n "$model_abbr" ]; then
  case "$model_tier" in
    opus-best)
      sections+=("$(printf "${BLUE}🧠 %s${RESET}" "$model_abbr")")
      ;;
    sonnet)
      sections+=("$(printf "${ORANGE}🐢 %s${RESET}" "$model_abbr")")
      ;;
    haiku)
      sections+=("$(printf "${RED}⚠️ %s${RESET}" "$model_abbr")")
      ;;
    *)
      sections+=("$(printf "%s" "$model_abbr")")
      ;;
  esac
fi

# Session: name or truncated ID
if [ -n "$session_name" ]; then
  sections+=("$(printf "${DIM}%s${RESET}" "$session_name")")
elif [ -n "$session_id_short" ]; then
  sections+=("$(printf "${DIM}%s${RESET}" "$session_id_short")")
fi

# Dir + git branch (combined)
dir_part="$(printf "${CYAN}%s${RESET}" "$cwd_display")"
if [ -n "$git_branch" ]; then
  dir_part="${dir_part} $(printf "${YELLOW}%s${RESET}" "$git_branch")"
fi
sections+=("$dir_part")

# LOC tracking (+added / -removed)
if [ "$lines_added" -gt 0 ] || [ "$lines_removed" -gt 0 ]; then
  loc_part=""
  if [ "$lines_added" -gt 0 ]; then
    loc_part="$(printf "${GREEN}+%s${RESET}" "$lines_added")"
  fi
  if [ "$lines_removed" -gt 0 ]; then
    [ -n "$loc_part" ] && loc_part="${loc_part} "
    loc_part="${loc_part}$(printf "${RED}-%s${RESET}" "$lines_removed")"
  fi
  sections+=("$loc_part")
fi

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

# Session cost
if [ -n "$total_cost" ] && [ "$total_cost" != "0" ]; then
  cost_formatted=$(printf '$%.2f' "$total_cost")
  sections+=("$(printf "${DIM}%s${RESET}" "$cost_formatted")")
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
