#!/usr/bin/env bash
# CCGM - TUI utilities with gum progressive enhancement
# If gum is available: styled prompts, spinners, filterable lists
# If not: ANSI-colored bash fallback

# --- Color constants ---
readonly UI_RED='\033[0;31m'
readonly UI_GREEN='\033[0;32m'
readonly UI_YELLOW='\033[0;33m'
readonly UI_BLUE='\033[0;34m'
readonly UI_MAGENTA='\033[0;35m'
readonly UI_CYAN='\033[0;36m'
readonly UI_BOLD='\033[1m'
readonly UI_DIM='\033[2m'
readonly UI_RESET='\033[0m'

# --- Detection ---
_has_gum() {
  command -v gum &>/dev/null
}

_is_non_interactive() {
  [ "${CCGM_NON_INTERACTIVE:-}" = "1" ]
}

# --- Banner ---
ui_banner() {
  if _has_gum; then
    gum style \
      --border double \
      --border-foreground 99 \
      --padding "1 3" \
      --margin "1 0" \
      --align center \
      "  CCGM  " \
      "Claude Code God Mode" \
      "" \
      "Modular configuration for Claude Code"
  else
    echo ""
    echo -e "${UI_MAGENTA}${UI_BOLD}======================================${UI_RESET}"
    echo -e "${UI_MAGENTA}${UI_BOLD}            CCGM${UI_RESET}"
    echo -e "${UI_MAGENTA}${UI_BOLD}      Claude Code God Mode${UI_RESET}"
    echo -e "${UI_MAGENTA}${UI_BOLD}======================================${UI_RESET}"
    echo -e "${UI_DIM}  Modular configuration for Claude Code${UI_RESET}"
    echo ""
  fi
}

# --- Section header ---
# Usage: ui_header "Section Title"
ui_header() {
  local title="$1"
  if _has_gum; then
    echo ""
    gum style --foreground 99 --bold -- "--- $title ---"
  else
    echo ""
    echo -e "${UI_CYAN}${UI_BOLD}--- $title ---${UI_RESET}"
  fi
}

# --- Status messages ---
ui_success() {
  if _has_gum; then
    gum style --foreground 2 -- "  $1"
  else
    echo -e "${UI_GREEN}  $1${UI_RESET}"
  fi
}

ui_error() {
  if _has_gum; then
    gum style --foreground 1 -- "  $1"
  else
    echo -e "${UI_RED}  $1${UI_RESET}"
  fi
}

ui_warn() {
  if _has_gum; then
    gum style --foreground 3 -- "  $1"
  else
    echo -e "${UI_YELLOW}  $1${UI_RESET}"
  fi
}

ui_info() {
  if _has_gum; then
    gum style --foreground 4 -- "  $1"
  else
    echo -e "${UI_BLUE}  $1${UI_RESET}"
  fi
}

# --- Confirm (yes/no) ---
# Usage: ui_confirm "Are you sure?" && echo "yes" || echo "no"
# Optional second arg: default (yes/no)
ui_confirm() {
  local prompt="$1"
  local default="${2:-yes}"

  if _is_non_interactive; then
    # Auto-confirm with default in non-interactive mode
    if [ "$default" = "yes" ]; then return 0; else return 1; fi
  fi

  if _has_gum; then
    if [ "$default" = "yes" ]; then
      gum confirm --default=yes "$prompt"
    else
      gum confirm --default=no "$prompt"
    fi
    return $?
  else
    local yn_hint
    if [ "$default" = "yes" ]; then
      yn_hint="[Y/n]"
    else
      yn_hint="[y/N]"
    fi
    while true; do
      echo -en "${UI_CYAN}? ${UI_RESET}${UI_BOLD}$prompt${UI_RESET} $yn_hint "
      read -r answer
      case "${answer,,}" in
        y|yes) return 0 ;;
        n|no) return 1 ;;
        "")
          if [ "$default" = "yes" ]; then return 0; else return 1; fi
          ;;
        *) echo -e "${UI_YELLOW}  Please answer yes or no.${UI_RESET}" ;;
      esac
    done
  fi
}

# --- Text input ---
# Usage: result=$(ui_input "GitHub username" "default_value")
ui_input() {
  local prompt="$1"
  local default="$2"

  if _is_non_interactive; then
    # Return default value in non-interactive mode
    echo "${default:-}"
    return 0
  fi

  if _has_gum; then
    echo -e "${UI_CYAN}? ${UI_RESET}${UI_BOLD}$prompt${UI_RESET}" >&2
    local args=(--placeholder "$prompt")
    if [ -n "$default" ]; then
      args+=(--value "$default")
    fi
    local result
    result=$(gum input "${args[@]}")
    if [ -z "$result" ] && [ -n "$default" ]; then
      echo "$default"
    else
      echo "$result"
    fi
  else
    local display_default=""
    if [ -n "$default" ]; then
      display_default=" ${UI_DIM}($default)${UI_RESET}"
    fi
    echo -en "${UI_CYAN}? ${UI_RESET}${UI_BOLD}$prompt${UI_RESET}$display_default: " >&2
    local answer
    read -r answer
    if [ -z "$answer" ] && [ -n "$default" ]; then
      echo "$default"
    else
      echo "$answer"
    fi
  fi
}

# --- Single select ---
# Usage: result=$(ui_choose "Pick one" "option1" "option2" "option3")
ui_choose() {
  local prompt="$1"
  shift
  local options=("$@")

  if _is_non_interactive; then
    # Return first option in non-interactive mode
    echo "${options[0]}"
    return 0
  fi

  if _has_gum; then
    echo -e "${UI_CYAN}? ${UI_RESET}${UI_BOLD}$prompt${UI_RESET}" >&2
    printf '%s\n' "${options[@]}" | gum choose
  else
    echo -e "${UI_CYAN}? ${UI_RESET}${UI_BOLD}$prompt${UI_RESET}" >&2
    local i=1
    for opt in "${options[@]}"; do
      echo -e "  ${UI_CYAN}$i)${UI_RESET} $opt" >&2
    done
    while true; do
      echo -en "${UI_CYAN}> ${UI_RESET}Enter number (1-${#options[@]}): " >&2
      local choice
      read -r choice
      if [[ "$choice" =~ ^[0-9]+$ ]] && [ "$choice" -ge 1 ] && [ "$choice" -le "${#options[@]}" ]; then
        echo "${options[$((choice-1))]}"
        return 0
      fi
      echo -e "${UI_YELLOW}  Invalid choice, try again.${UI_RESET}" >&2
    done
  fi
}

# --- Multi-select ---
# Usage: result=$(ui_multichoose "Pick modules" "mod1" "mod2" "mod3")
# Returns newline-separated list of selected items
ui_multichoose() {
  local prompt="$1"
  shift
  local options=("$@")

  if _has_gum; then
    echo -e "${UI_CYAN}? ${UI_RESET}${UI_BOLD}$prompt${UI_RESET}" >&2
    printf '%s\n' "${options[@]}" | gum choose --no-limit
  else
    echo -e "${UI_CYAN}? ${UI_RESET}${UI_BOLD}$prompt${UI_RESET}" >&2
    echo -e "${UI_DIM}  Enter numbers separated by spaces, or 'a' for all${UI_RESET}" >&2
    local i=1
    for opt in "${options[@]}"; do
      echo -e "  ${UI_CYAN}$i)${UI_RESET} $opt" >&2
    done
    echo -en "${UI_CYAN}> ${UI_RESET}Selection: " >&2
    local input
    read -r input
    if [ "$input" = "a" ] || [ "$input" = "all" ]; then
      printf '%s\n' "${options[@]}"
      return 0
    fi
    local selected=()
    for num in $input; do
      if [[ "$num" =~ ^[0-9]+$ ]] && [ "$num" -ge 1 ] && [ "$num" -le "${#options[@]}" ]; then
        selected+=("${options[$((num-1))]}")
      fi
    done
    printf '%s\n' "${selected[@]}"
  fi
}

# --- Spinner ---
# Usage: ui_spin "Installing modules..." some_command arg1 arg2
ui_spin() {
  local title="$1"
  shift

  if _has_gum; then
    gum spin --spinner dot --title "$title" -- "$@"
  else
    echo -en "${UI_CYAN}  $title${UI_RESET} " >&2
    "$@" &>/dev/null &
    local pid=$!
    local spin_chars='/-\|'
    local i=0
    while kill -0 "$pid" 2>/dev/null; do
      i=$(( (i+1) % 4 ))
      printf "\b${spin_chars:$i:1}" >&2
      sleep 0.1
    done
    wait "$pid"
    local exit_code=$?
    printf "\b " >&2
    echo "" >&2
    return $exit_code
  fi
}

# --- File preview ---
# Usage: ui_preview_file "/path/to/file"
ui_preview_file() {
  local filepath="$1"
  local relpath="${2:-$filepath}"
  echo -e "  ${UI_DIM}$relpath${UI_RESET}"
}

# --- Divider ---
ui_divider() {
  if _has_gum; then
    gum style --foreground 240 -- "$(printf '%.0s-' {1..50})"
  else
    echo -e "${UI_DIM}$(printf '%.0s-' {1..50})${UI_RESET}"
  fi
}

# --- List item ---
# Usage: ui_list_item "module-name" "Description text"
ui_list_item() {
  local name="$1"
  local desc="$2"
  if _has_gum; then
    gum style -- "  $(gum style --foreground 2 --bold -- "$name")  $desc"
  else
    echo -e "  ${UI_GREEN}${UI_BOLD}$name${UI_RESET}  $desc"
  fi
}
