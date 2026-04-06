#!/usr/bin/env bash
# ccgm-headless-install.sh — Non-interactive CCGM installer for cloud agent users.
#
# Installs a CCGM preset into a target user's ~/.claude/ directory by copying
# rule and command files from the CCGM repo. No interactive prompts, no template
# expansion (cloud agents don't need user-specific config).
#
# Usage:
#   ccgm-headless-install.sh <ccgm-repo-path> <preset-name> <target-user-home>
#
# Example:
#   ccgm-headless-install.sh /opt/ccgm/repo cloud-agent /home/agent-0
#
# This script is designed to run ON the VM (not from the orchestrator).
set -euo pipefail

if [[ $# -lt 3 ]]; then
  echo "Usage: $0 <ccgm-repo-path> <preset-name> <target-user-home>" >&2
  exit 1
fi

CCGM_REPO="$1"
PRESET_NAME="$2"
TARGET_HOME="$3"

CLAUDE_DIR="${TARGET_HOME}/.claude"
PRESET_FILE="${CCGM_REPO}/presets/${PRESET_NAME}.json"

if [[ ! -f "${PRESET_FILE}" ]]; then
  echo "Error: preset not found: ${PRESET_FILE}" >&2
  exit 1
fi

if [[ ! -d "${CCGM_REPO}/modules" ]]; then
  echo "Error: CCGM modules directory not found: ${CCGM_REPO}/modules" >&2
  exit 1
fi

# Parse preset JSON to get module list
if ! command -v jq &>/dev/null; then
  echo "Error: jq is required but not installed" >&2
  exit 1
fi

mapfile -t MODULES < <(jq -r '.[]' "${PRESET_FILE}")

echo "==> Installing CCGM preset '${PRESET_NAME}' to ${CLAUDE_DIR}"
echo "    Modules: ${MODULES[*]}"

# Create target directories
mkdir -p "${CLAUDE_DIR}/rules"
mkdir -p "${CLAUDE_DIR}/commands"

INSTALLED_RULES=0
INSTALLED_COMMANDS=0

for module in "${MODULES[@]}"; do
  MODULE_DIR="${CCGM_REPO}/modules/${module}"
  MANIFEST="${MODULE_DIR}/module.json"

  if [[ ! -f "${MANIFEST}" ]]; then
    echo "  WARN: module '${module}' not found, skipping"
    continue
  fi

  echo "  --> Installing module: ${module}"

  # Extract file mappings from module.json
  # Each file entry has: source path (key), target path, and type
  while IFS=$'\t' read -r src target ftype; do
    SRC_PATH="${MODULE_DIR}/${src}"

    if [[ ! -f "${SRC_PATH}" ]]; then
      echo "    WARN: source file not found: ${SRC_PATH}"
      continue
    fi

    case "${ftype}" in
      rule)
        cp "${SRC_PATH}" "${CLAUDE_DIR}/${target}"
        INSTALLED_RULES=$((INSTALLED_RULES + 1))
        ;;
      command)
        cp "${SRC_PATH}" "${CLAUDE_DIR}/${target}"
        INSTALLED_COMMANDS=$((INSTALLED_COMMANDS + 1))
        ;;
      # Skip lib, hook, settings, and other non-rule/command types
      # Cloud agents get lib scripts via the cloud-dispatch module's own paths
      *)
        ;;
    esac
  done < <(jq -r '.files | to_entries[] | [.key, .value.target, .value.type] | @tsv' "${MANIFEST}")
done

echo "==> CCGM headless install complete"
echo "    Rules installed: ${INSTALLED_RULES}"
echo "    Commands installed: ${INSTALLED_COMMANDS}"
echo "    Target: ${CLAUDE_DIR}"
