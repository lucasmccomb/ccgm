#!/usr/bin/env bash
# Discover session files across Claude Code and Codex.
#
# Usage: discover-sessions.sh <repo-name> <days> [--platform claude|codex]
#
# Outputs one file path per line. Safe in both bash and zsh (all globs guarded).
# Pass output to extract-metadata.py:
#   bash discover-sessions.sh <repo-name> 7 | tr '\n' '\0' | xargs -0 python3 extract-metadata.py --cwd-filter <repo-name>
#
# Arguments:
#   repo-name  Folder name of the repo (e.g., "my-repo"). Used for directory matching.
#   days       Scan window in days (e.g., 7). Files older than this are skipped.
#   --platform Restrict to a single platform. Omit to search all.

set -euo pipefail

REPO_NAME="${1:?Usage: discover-sessions.sh <repo-name> <days> [--platform claude|codex]}"
DAYS="${2:?Usage: discover-sessions.sh <repo-name> <days> [--platform claude|codex]}"
PLATFORM="all"

# Parse optional --platform flag
shift 2
while [ $# -gt 0 ]; do
    case "$1" in
        --platform) PLATFORM="$2"; shift 2 ;;
        *) shift ;;
    esac
done

# --- Claude Code ---
discover_claude() {
    local base="$HOME/.claude/projects"
    [ -d "$base" ] || return 0

    # Find all project dirs matching repo name (CWD-encoded: / -> -)
    for dir in "$base"/*"$REPO_NAME"*/; do
        [ -d "$dir" ] || continue
        find "$dir" -maxdepth 1 -name "*.jsonl" -mtime "-${DAYS}" 2>/dev/null
    done
}

# --- Codex ---
discover_codex() {
    # Codex sessions are not organized by project directory. Discover by mtime
    # across the whole tree, then let extract-metadata.py filter by --cwd-filter.
    for base in "$HOME/.codex/sessions" "$HOME/.agents/sessions"; do
        [ -d "$base" ] || continue
        find "$base" -name "*.jsonl" -mtime "-${DAYS}" 2>/dev/null
    done
}

# --- Dispatch ---
case "$PLATFORM" in
    claude)  discover_claude ;;
    codex)   discover_codex ;;
    all)
        discover_claude
        discover_codex
        ;;
    *)
        echo "Unknown platform: $PLATFORM (expected claude|codex|all)" >&2
        exit 1
        ;;
esac
