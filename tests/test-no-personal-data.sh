#!/usr/bin/env bash
set -euo pipefail

# CCGM Personal Data Check
# Ensures no personal/private data leaked into public repo files

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

echo "=== CCGM Personal Data Check ==="
echo ""

# Patterns that should never appear in public repo files.
# These cover: usernames, personal paths, Supabase project refs,
# service URLs, Tailscale hostnames/IPs, and personal device names.
PATTERN='lucasmccomb|Lucas McComb|@lucasmccomb|/Users/lem|lem-personal|lem-agent-logs|hyhaowdndehadgcwjxtw|hwoxbllmdqvavxthrlql|eluketronic\.app\.n8n\.cloud|lem-mbp|100\.113\.180\.79|iphone171'

# Directories and files to scan
SCAN_TARGETS=(
  "$REPO_ROOT/modules/"
  "$REPO_ROOT/lib/"
  "$REPO_ROOT/presets/"
  "$REPO_ROOT/start.sh"
  "$REPO_ROOT/update.sh"
  "$REPO_ROOT/uninstall.sh"
  "$REPO_ROOT/README.md"
  "$REPO_ROOT/CONTRIBUTING.md"
  "$REPO_ROOT/CLAUDE.md"
)

# Build list of targets that actually exist
existing_targets=()
for t in "${SCAN_TARGETS[@]}"; do
  if [ -e "$t" ]; then
    existing_targets+=("$t")
  fi
done

if [ ${#existing_targets[@]} -eq 0 ]; then
  echo "WARNING: No scan targets found. Is this the right repo?"
  exit 1
fi

echo "Scanning ${#existing_targets[@]} targets for personal data..."
echo ""

# Run the check
# grep returns exit 0 if matches found (bad), 1 if no matches (good)
# Exclude README.md from username check (it contains the actual repo clone URL)
matches=""
set +e
matches=$(grep -rlE "$PATTERN" \
  --include="*.md" --include="*.json" --include="*.py" --include="*.sh" --include="*.yml" \
  "${existing_targets[@]}" 2>/dev/null | grep -v "README.md$" || true)

# Also check README.md separately with a pattern that excludes the repo URL
readme_pattern='/Users/lem|lem-personal|lem-agent-logs|hyhaowdndehadgcwjxtw|hwoxbllmdqvavxthrlql|eluketronic\.app\.n8n\.cloud|lem-mbp|100\.113\.180\.79|iphone171'
readme_matches=$(grep -lE "$readme_pattern" "$REPO_ROOT/README.md" 2>/dev/null || true)
if [ -n "$readme_matches" ]; then
  matches="${matches:+$matches
}$readme_matches"
fi
set -e

if [ -n "$matches" ]; then
  echo "FAIL: Personal data found in the following files:"
  echo ""
  echo "$matches" | while IFS= read -r f; do
    echo "  $f"
    # Show matching lines (with context)
    grep -nE "$PATTERN" "$f" 2>/dev/null | head -5 | while IFS= read -r line; do
      echo "    $line"
    done
  done
  echo ""
  echo "Remove all personal data before committing."
  exit 1
else
  echo "PASS: No personal data found"
  exit 0
fi
