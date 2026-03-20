#!/usr/bin/env bash
# CCGM - Pure bash TUI with ANSI escape sequences
# Arrow-key navigation menus, no external dependencies

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

_is_non_interactive() {
  [ "${CCGM_NON_INTERACTIVE:-}" = "1" ]
}

# --- Banner ---
ui_banner() {
  echo ""
  echo -e "${UI_MAGENTA}${UI_BOLD}======================================${UI_RESET}"
  echo -e "${UI_MAGENTA}${UI_BOLD}            CCGM${UI_RESET}"
  echo -e "${UI_MAGENTA}${UI_BOLD}      Claude Code God Mode${UI_RESET}"
  echo -e "${UI_MAGENTA}${UI_BOLD}======================================${UI_RESET}"
  echo -e "${UI_DIM}  Modular configuration for Claude Code${UI_RESET}"
  echo ""
}

# --- Section header ---
# Usage: ui_header "Section Title"
ui_header() {
  local title="$1"
  echo ""
  echo -e "${UI_CYAN}${UI_BOLD}--- $title ---${UI_RESET}"
}

# --- Status messages ---
ui_success() {
  echo -e "${UI_GREEN}  $1${UI_RESET}"
}

ui_error() {
  echo -e "${UI_RED}  $1${UI_RESET}"
}

ui_warn() {
  echo -e "${UI_YELLOW}  $1${UI_RESET}"
}

ui_info() {
  echo -e "${UI_BLUE}  $1${UI_RESET}"
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
}

# --- Read a single keypress (handles escape sequences for arrow keys) ---
# Sets global _KEY to: "up", "down", "enter", "space", "a", or the character
_read_key() {
  local char
  IFS= read -rsn1 char < /dev/tty

  case "$char" in
    $'\x1b')
      # Escape sequence - read next two chars for arrow keys
      local seq1 seq2
      IFS= read -rsn1 -t 0.1 seq1 < /dev/tty
      IFS= read -rsn1 -t 0.1 seq2 < /dev/tty
      case "${seq1}${seq2}" in
        "[A") _KEY="up" ;;
        "[B") _KEY="down" ;;
        *)    _KEY="escape" ;;
      esac
      ;;
    "")
      _KEY="enter"
      ;;
    " ")
      _KEY="space"
      ;;
    *)
      _KEY="$char"
      ;;
  esac
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

  # Save terminal state and enable raw mode on /dev/tty
  local original_stty
  original_stty=$(stty -g < /dev/tty)
  stty -echo -icanon < /dev/tty

  # Restore terminal on exit (works in subshell from $())
  trap "stty '$original_stty' < /dev/tty 2>/dev/null; printf '\\033[?25h' > /dev/tty" EXIT
  trap "stty '$original_stty' < /dev/tty 2>/dev/null; printf '\\033[?25h' > /dev/tty; exit 130" INT

  # Hide cursor
  printf '\033[?25l' > /dev/tty

  # Print prompt
  printf "${UI_CYAN}? ${UI_RESET}${UI_BOLD}%s${UI_RESET} ${UI_DIM}(arrows navigate, enter selects)${UI_RESET}\n" "$prompt" > /dev/tty

  local selected=0
  local count=${#options[@]}
  local i

  # Initial render
  for ((i = 0; i < count; i++)); do
    if [ $i -eq $selected ]; then
      printf "  ${UI_CYAN}${UI_BOLD}▸ %s${UI_RESET}\n" "${options[$i]}" > /dev/tty
    else
      printf "    %s\n" "${options[$i]}" > /dev/tty
    fi
  done

  while true; do
    _read_key
    local moved=false

    case "$_KEY" in
      up)
        if [ $selected -gt 0 ]; then
          selected=$((selected - 1))
          moved=true
        fi
        ;;
      down)
        if [ $selected -lt $((count - 1)) ]; then
          selected=$((selected + 1))
          moved=true
        fi
        ;;
      enter)
        # Show cursor
        printf '\033[?25h' > /dev/tty
        # Output result to stdout (captured by $())
        echo "${options[$selected]}"
        return 0
        ;;
    esac

    if [ "$moved" = true ]; then
      # Move cursor up to top of list and redraw
      printf "\033[%dA" "$count" > /dev/tty
      for ((i = 0; i < count; i++)); do
        printf "\r\033[2K" > /dev/tty
        if [ $i -eq $selected ]; then
          printf "  ${UI_CYAN}${UI_BOLD}▸ %s${UI_RESET}\n" "${options[$i]}" > /dev/tty
        else
          printf "    %s\n" "${options[$i]}" > /dev/tty
        fi
      done
    fi
  done
}

# --- Multi-select ---
# Usage: result=$(ui_multichoose "Pick modules" "mod1" "mod2" "mod3")
# Returns newline-separated list of selected items
ui_multichoose() {
  local prompt="$1"
  shift
  local options=("$@")

  if _is_non_interactive; then
    # Return all options in non-interactive mode
    printf '%s\n' "${options[@]}"
    return 0
  fi

  # Save terminal state and enable raw mode on /dev/tty
  local original_stty
  original_stty=$(stty -g < /dev/tty)
  stty -echo -icanon < /dev/tty

  # Restore terminal on exit (works in subshell from $())
  trap "stty '$original_stty' < /dev/tty 2>/dev/null; printf '\\033[?25h' > /dev/tty" EXIT
  trap "stty '$original_stty' < /dev/tty 2>/dev/null; printf '\\033[?25h' > /dev/tty; exit 130" INT

  # Hide cursor
  printf '\033[?25l' > /dev/tty

  # Print prompt
  printf "${UI_CYAN}? ${UI_RESET}${UI_BOLD}%s${UI_RESET} ${UI_DIM}(arrows navigate, space toggles, a=all, enter confirms)${UI_RESET}\n" "$prompt" > /dev/tty

  local cursor=0
  local count=${#options[@]}
  local i
  local checked=()
  for ((i = 0; i < count; i++)); do
    checked+=("false")
  done

  # Initial render
  for ((i = 0; i < count; i++)); do
    local marker="[ ]"
    [ "${checked[$i]}" = "true" ] && marker="[✓]"
    if [ $i -eq $cursor ]; then
      printf "  ${UI_CYAN}${UI_BOLD}▸ %s %s${UI_RESET}\n" "$marker" "${options[$i]}" > /dev/tty
    else
      printf "    %s %s\n" "$marker" "${options[$i]}" > /dev/tty
    fi
  done

  while true; do
    _read_key

    case "$_KEY" in
      up)
        if [ $cursor -gt 0 ]; then
          cursor=$((cursor - 1))
        fi
        ;;
      down)
        if [ $cursor -lt $((count - 1)) ]; then
          cursor=$((cursor + 1))
        fi
        ;;
      space)
        if [ "${checked[$cursor]}" = "true" ]; then
          checked[$cursor]="false"
        else
          checked[$cursor]="true"
        fi
        ;;
      a)
        # Toggle all: if all checked, uncheck all; otherwise check all
        local all_checked=true
        for ((i = 0; i < count; i++)); do
          if [ "${checked[$i]}" = "false" ]; then
            all_checked=false
            break
          fi
        done
        for ((i = 0; i < count; i++)); do
          if [ "$all_checked" = true ]; then
            checked[$i]="false"
          else
            checked[$i]="true"
          fi
        done
        ;;
      enter)
        # Show cursor
        printf '\033[?25h' > /dev/tty
        # Show summary on tty
        local sel_count=0
        for ((i = 0; i < count; i++)); do
          [ "${checked[$i]}" = "true" ] && sel_count=$((sel_count + 1))
        done
        printf "  ${UI_GREEN}✓ %d selected${UI_RESET}\n" "$sel_count" > /dev/tty
        # Output selected items to stdout (captured by $())
        for ((i = 0; i < count; i++)); do
          if [ "${checked[$i]}" = "true" ]; then
            echo "${options[$i]}"
          fi
        done
        return 0
        ;;
      *)
        # Ignore other keys
        continue
        ;;
    esac

    # Redraw menu
    printf "\033[%dA" "$count" > /dev/tty
    for ((i = 0; i < count; i++)); do
      printf "\r\033[2K" > /dev/tty
      local marker="[ ]"
      [ "${checked[$i]}" = "true" ] && marker="[✓]"
      if [ $i -eq $cursor ]; then
        printf "  ${UI_CYAN}${UI_BOLD}▸ %s %s${UI_RESET}\n" "$marker" "${options[$i]}" > /dev/tty
      else
        printf "    %s %s\n" "$marker" "${options[$i]}" > /dev/tty
      fi
    done
  done
}

# --- Spinner ---
# Usage: ui_spin "Installing modules..." some_command arg1 arg2
ui_spin() {
  local title="$1"
  shift

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
  echo -e "${UI_DIM}$(printf '%.0s-' {1..50})${UI_RESET}"
}

# --- List item ---
# Usage: ui_list_item "module-name" "Description text"
ui_list_item() {
  local name="$1"
  local desc="$2"
  echo -e "  ${UI_GREEN}${UI_BOLD}$name${UI_RESET}  $desc"
}
