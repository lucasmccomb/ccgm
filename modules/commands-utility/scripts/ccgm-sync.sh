#!/usr/bin/env bash
# ccgm-sync.sh: Reverse-sync local ~/.claude changes back to CCGM module sources
#
# Reads .ccgm-manifest.json to find managed files, compares local vs module source,
# copies drifted files back, and reports unmanaged files.
#
# Usage:
#   ccgm-sync.sh [--dry]    Preview what would change
#   ccgm-sync.sh             Sync, commit, push, and merge

set -euo pipefail

MANIFEST="${HOME}/.claude/.ccgm-manifest.json"
DRY_RUN=false

if [[ "${1:-}" == "--dry" ]]; then
  DRY_RUN=true
fi

# --- Validate prerequisites ---
if [ ! -f "$MANIFEST" ]; then
  echo "ERROR: CCGM manifest not found at $MANIFEST"
  echo "Is CCGM installed? Run start.sh first."
  exit 1
fi

if ! command -v jq &>/dev/null; then
  echo "ERROR: jq is required but not found"
  exit 1
fi

CCGM_ROOT=$(jq -r '.ccgmRoot' "$MANIFEST")
LINK_MODE=$(jq -r '.linkMode // false' "$MANIFEST")

if [ ! -d "$CCGM_ROOT" ]; then
  echo "ERROR: CCGM root not found: $CCGM_ROOT"
  exit 1
fi

if [ "$LINK_MODE" = "true" ]; then
  echo "CCGM is in link mode - files are already symlinked to module sources."
  echo "No reverse-sync needed. Changes are automatically in the repo."
  echo ""
  echo "Just commit and push:"
  echo "  cd $CCGM_ROOT && git add -A && git commit && git push"
  exit 0
fi

# --- Collect drifted files ---
echo "Checking for local changes to CCGM-managed files..."
echo ""

DRIFTED=()
DRIFTED_PAIRS=()  # "module|src|target" triples

MODULES=$(jq -r '.modules[]?' "$MANIFEST")

while IFS= read -r mod; do
  [ -z "$mod" ] && continue
  MODULE_JSON="${CCGM_ROOT}/modules/${mod}/module.json"
  [ ! -f "$MODULE_JSON" ] && continue

  # Read file mappings from module.json
  while IFS= read -r file_entry; do
    src=$(echo "$file_entry" | jq -r '.src')
    target=$(echo "$file_entry" | jq -r '.target')
    template=$(echo "$file_entry" | jq -r '.template')
    merge=$(echo "$file_entry" | jq -r '.merge // false')

    full_src="${CCGM_ROOT}/modules/${mod}/${src}"
    full_target="${HOME}/.claude/${target}"

    # Skip templates and merge files (they're generated, not 1:1)
    if [ "$template" = "true" ] || [ "$merge" = "true" ]; then
      continue
    fi

    # Skip if either file doesn't exist
    [ ! -f "$full_src" ] && continue
    [ ! -f "$full_target" ] && continue

    # Compare
    if ! diff -q "$full_src" "$full_target" &>/dev/null; then
      DRIFTED+=("$target")
      DRIFTED_PAIRS+=("${mod}|${src}|${target}")

      if $DRY_RUN; then
        echo "CHANGED: $target (module: $mod)"
        diff --color=auto "$full_src" "$full_target" 2>/dev/null | head -30 || true
        echo ""
      fi
    fi
  done < <(jq -r '.files | to_entries[] | {src: .key, target: .value.target, template: (.value.template // false), merge: (.value.merge // false)} | @json' "$MODULE_JSON" 2>/dev/null)
done <<< "$MODULES"

# --- Check for unmanaged files ---
echo "Checking for new files not tracked by CCGM..."

MANAGED_TARGETS=()
while IFS= read -r mod; do
  [ -z "$mod" ] && continue
  MODULE_JSON="${CCGM_ROOT}/modules/${mod}/module.json"
  [ ! -f "$MODULE_JSON" ] && continue
  while IFS= read -r t; do
    MANAGED_TARGETS+=("$t")
  done < <(jq -r '.files | to_entries[] | .value.target' "$MODULE_JSON" 2>/dev/null)
done <<< "$MODULES"

UNMANAGED=()
# Check commands/
for f in "${HOME}/.claude/commands/"*.md; do
  [ ! -f "$f" ] && continue
  rel="commands/$(basename "$f")"
  found=false
  for mt in "${MANAGED_TARGETS[@]}"; do
    if [ "$mt" = "$rel" ]; then found=true; break; fi
  done
  if ! $found; then
    UNMANAGED+=("$rel")
  fi
done

# Check rules/
for f in "${HOME}/.claude/rules/"*.md; do
  [ ! -f "$f" ] && continue
  rel="rules/$(basename "$f")"
  found=false
  for mt in "${MANAGED_TARGETS[@]}"; do
    if [ "$mt" = "$rel" ]; then found=true; break; fi
  done
  if ! $found; then
    UNMANAGED+=("$rel")
  fi
done

# Check hooks/
for f in "${HOME}/.claude/hooks/"*.py; do
  [ ! -f "$f" ] && continue
  rel="hooks/$(basename "$f")"
  found=false
  for mt in "${MANAGED_TARGETS[@]}"; do
    if [ "$mt" = "$rel" ]; then found=true; break; fi
  done
  if ! $found; then
    UNMANAGED+=("$rel")
  fi
done

# --- Report ---
echo "=============================="
echo "  CCGM Sync Summary"
echo "=============================="
echo ""

if [ ${#DRIFTED[@]} -eq 0 ]; then
  echo "No drifted files - CCGM modules are in sync with local."
else
  echo "Drifted files (${#DRIFTED[@]}):"
  for f in "${DRIFTED[@]}"; do
    echo "  * $f"
  done
fi
echo ""

if [ ${#UNMANAGED[@]} -gt 0 ]; then
  echo "Unmanaged files (${#UNMANAGED[@]}) - not tracked by any CCGM module:"
  for f in "${UNMANAGED[@]}"; do
    echo "  ? $f"
  done
  echo ""
  echo "To add these to CCGM, create a new module or add to an existing one."
fi

if $DRY_RUN; then
  echo ""
  echo "Dry run complete. Run without --dry to apply changes."
  exit 0
fi

# --- Apply: copy local -> module source ---
if [ ${#DRIFTED[@]} -eq 0 ]; then
  echo ""
  echo "Nothing to sync."
  exit 0
fi

echo ""
echo "Syncing ${#DRIFTED[@]} file(s) back to CCGM modules..."

for pair in "${DRIFTED_PAIRS[@]}"; do
  IFS='|' read -r mod src target <<< "$pair"
  full_src="${CCGM_ROOT}/modules/${mod}/${src}"
  full_target="${HOME}/.claude/${target}"
  cp "$full_target" "$full_src"
  echo "  Copied: $target -> modules/${mod}/${src}"
done

# --- Commit, push, merge ---
echo ""
echo "Committing changes to CCGM repo..."

cd "$CCGM_ROOT"

# Check current branch
CURRENT_BRANCH=$(git symbolic-ref --short HEAD 2>/dev/null || echo "detached")

if [ "$CURRENT_BRANCH" = "main" ]; then
  # Direct commit on main (simple sync)
  git add -A
  if git diff --cached --quiet; then
    echo "No changes to commit (files already match)."
    exit 0
  fi
  git commit -m "sync: reverse-sync local config changes ($(date +%Y-%m-%d))"
  echo "Pushing to remote..."
  git push origin main
  echo ""
  echo "Done! CCGM repo updated on main."
else
  # On a branch - commit and push branch
  git add -A
  if git diff --cached --quiet; then
    echo "No changes to commit."
    exit 0
  fi
  git commit -m "sync: reverse-sync local config changes ($(date +%Y-%m-%d))"
  echo "Pushing branch $CURRENT_BRANCH..."
  git push -u origin "$CURRENT_BRANCH"
  echo ""
  echo "Branch pushed. Create a PR to merge into main:"
  echo "  gh pr create --title 'sync: local config changes' --body 'Reverse-sync from local ~/.claude'"
fi

echo ""
echo "Sync complete."
