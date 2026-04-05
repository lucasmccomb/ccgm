#!/usr/bin/env bash
# CCGM - Settings.json deep merge via jq
# Merges partial settings into a target settings.json

# --- Check jq availability ---
_require_jq() {
  if ! command -v jq &>/dev/null; then
    echo "WARNING: jq is required for settings.json merging but not found." >&2
    echo "  Install: brew install jq (macOS) or apt install jq (Linux)" >&2
    return 1
  fi
  return 0
}

# --- Deep merge two JSON files ---
# Usage: merge_settings "/target/settings.json" "/partial/settings.json"
# Merges partial into target with special handling for:
# - permissions.allow: concatenate + deduplicate
# - permissions.deny: concatenate + deduplicate
# - hooks: deep merge (combine hook arrays by event type)
# - Everything else: recursive object merge (partial wins on conflicts)
merge_settings() {
  local target="$1"
  local partial="$2"

  _require_jq || return 1

  if [ ! -f "$partial" ]; then
    echo "WARNING: Partial settings file not found: $partial" >&2
    return 1
  fi

  # If target doesn't exist, just copy the partial
  if [ ! -f "$target" ]; then
    cp "$partial" "$target"
    return 0
  fi

  # Validate both files are valid JSON
  if ! jq empty "$target" 2>/dev/null; then
    echo "ERROR: Invalid JSON in target: $target" >&2
    return 1
  fi
  if ! jq empty "$partial" 2>/dev/null; then
    echo "ERROR: Invalid JSON in partial: $partial" >&2
    return 1
  fi

  # Perform the merge
  local merged
  merged=$(jq -s '
    # Custom deep merge function
    def deep_merge(a; b):
      a as $a | b as $b |
      if ($a | type) == "object" and ($b | type) == "object" then
        ($a | keys) + ($b | keys) | unique | map(
          . as $key |
          if ($key == "allow" or $key == "deny") and
             (($a[$key] | type) == "array") and
             (($b[$key] | type) == "array") then
            # Array merge with deduplication for allow/deny
            { ($key): (($a[$key] + $b[$key]) | unique) }
          elif ($key == "hooks" or $key == "enabledPlugins") and
               (($a[$key] | type) == "object") and
               (($b[$key] | type) == "object") then
            # Deep merge for hooks and plugins
            { ($key): deep_merge($a[$key]; $b[$key]) }
          elif (($a[$key] | type) == "object") and
               (($b[$key] | type) == "object") then
            # Recursive merge for objects
            { ($key): deep_merge($a[$key]; $b[$key]) }
          elif (($a[$key] | type) == "array") and
               (($b[$key] | type) == "array") then
            # For hook event arrays (PreToolUse, etc.), concatenate and deduplicate
            { ($key): ([$a[$key] + $b[$key] | .[] | tojson] | unique | [.[] | fromjson]) }
          elif $b | has($key) then
            { ($key): $b[$key] }
          else
            { ($key): $a[$key] }
          end
        ) | add // {}
      elif ($b | type) == "null" then
        $a
      else
        $b
      end;

    deep_merge(.[0]; .[1])
  ' "$target" "$partial" 2>/dev/null)

  if [ -z "$merged" ]; then
    echo "ERROR: Merge failed for $target + $partial" >&2
    return 1
  fi

  echo "$merged" | jq '.' > "$target"
}

# --- Initialize empty settings.json ---
# Creates a minimal valid settings.json if none exists
init_settings() {
  local target="$1"

  if [ -f "$target" ]; then
    return 0
  fi

  echo '{}' > "$target"
}
