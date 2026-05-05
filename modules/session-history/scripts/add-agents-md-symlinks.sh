#!/usr/bin/env bash
# add-agents-md-symlinks.sh
# Create AGENTS.md -> CLAUDE.md symlinks in a list of repos.
#
# The emerging AGENTS.md convention (2026) lets multiple agentic coding tools
# read project instructions from a single file. CCGM repos already have
# CLAUDE.md; symlinking AGENTS.md -> CLAUDE.md future-proofs them without
# duplicating content.
#
# Behavior:
# - Accepts a list of repo paths as arguments. If none provided, scans
#   sensible defaults under $CODE_DIR (default $HOME/code).
# - Skips any path that is not a directory containing CLAUDE.md.
# - Skips any path where AGENTS.md already exists as a non-symlink (warns).
# - If AGENTS.md is already a symlink, leaves it alone.
# - Otherwise creates a relative symlink AGENTS.md -> CLAUDE.md.

set -u

CODE_DIR="${CODE_DIR:-$HOME/code}"

DEFAULT_TARGETS=(
  "$CODE_DIR/ccgm"
  "$CODE_DIR/voxstr-repos/voxstr-0"
  "$CODE_DIR/voxstr-site-repos/voxstr-site-0"
  "$CODE_DIR/habitpro-ai-workspaces/habitpro-ai-w0/habitpro-ai-w0-c0"
  "$CODE_DIR/openslide-ai-repos/openslide-ai-0"
  "$CODE_DIR/lem-photo-repos/lem-photo-0"
  "$CODE_DIR/darkly-suite-repos/darkly-suite-0"
  "$CODE_DIR/lem-work-repos/lem-work-0"
  "$CODE_DIR/nadaproof"
)

if [ "$#" -gt 0 ]; then
  TARGETS=("$@")
else
  TARGETS=("${DEFAULT_TARGETS[@]}")
fi

CREATED=0
EXISTING_SYMLINK=0
BLOCKED_BY_REGULAR_FILE=0
SKIPPED_NO_CLAUDE_MD=0
SKIPPED_NOT_A_DIR=0

for target in "${TARGETS[@]}"; do
  if [ ! -d "$target" ]; then
    echo "skip: $target (not a directory)"
    SKIPPED_NOT_A_DIR=$((SKIPPED_NOT_A_DIR + 1))
    continue
  fi

  if [ ! -f "$target/CLAUDE.md" ]; then
    echo "skip: $target (no CLAUDE.md)"
    SKIPPED_NO_CLAUDE_MD=$((SKIPPED_NO_CLAUDE_MD + 1))
    continue
  fi

  agents_path="$target/AGENTS.md"

  if [ -L "$agents_path" ]; then
    echo "ok:   $agents_path (already a symlink)"
    EXISTING_SYMLINK=$((EXISTING_SYMLINK + 1))
    continue
  fi

  if [ -e "$agents_path" ]; then
    echo "warn: $agents_path exists as a regular file — leaving it alone"
    BLOCKED_BY_REGULAR_FILE=$((BLOCKED_BY_REGULAR_FILE + 1))
    continue
  fi

  ( cd "$target" && ln -s CLAUDE.md AGENTS.md )
  echo "new:  $agents_path -> CLAUDE.md"
  CREATED=$((CREATED + 1))
done

echo ""
echo "Summary:"
echo "  new symlinks created:      $CREATED"
echo "  existing symlinks kept:    $EXISTING_SYMLINK"
echo "  blocked (regular file):    $BLOCKED_BY_REGULAR_FILE"
echo "  skipped (no CLAUDE.md):    $SKIPPED_NO_CLAUDE_MD"
echo "  skipped (not a directory): $SKIPPED_NOT_A_DIR"
