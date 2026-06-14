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

# --- Record a CCGM-contributed merge partial as a sidecar ---
# Usage: record_merged_partial "/abs/target/settings.json" "/abs/partial.json" "$global_dir"
# Persists the exact (already template-expanded) partial that was merged into a
# merge target so uninstall can later subtract precisely those keys/entries.
# Sidecars live under "${store_dir}/.ccgm-merged/<sha>.json".
# Echoes a single-line JSON object: {"target": "...", "partial": "<sidecar>"}.
# Requires jq.
record_merged_partial() {
  local target="$1"
  local partial_src="$2"
  local store_dir="$3"

  command -v jq &>/dev/null || return 1

  local merged_dir="${store_dir}/.ccgm-merged"
  mkdir -p "$merged_dir"

  # Hash target + content so re-merging the same contribution is idempotent and
  # two different targets never collide.
  local sha
  if command -v shasum &>/dev/null; then
    sha=$( { printf '%s\0' "$target"; cat "$partial_src"; } | shasum -a 256 | awk '{print $1}')
  elif command -v sha256sum &>/dev/null; then
    sha=$( { printf '%s\0' "$target"; cat "$partial_src"; } | sha256sum | awk '{print $1}')
  else
    # Fallback: derive a stable-ish name from the target path only.
    sha=$(printf '%s' "$target" | cksum | awk '{print $1}')
  fi

  local sidecar="${merged_dir}/${sha}.json"
  cp "$partial_src" "$sidecar"

  jq -n -c --arg target "$target" --arg partial "$sidecar" \
    '{target: $target, partial: $partial}'
}

# --- Un-merge a CCGM-contributed partial out of a settings.json ---
# Usage: unmerge_settings "/target/settings.json" "/path/to/contributed-partial.json"
# Inverse of merge_settings. Removes ONLY the keys/entries CCGM contributed,
# leaving any user-authored keys intact. The partial is the exact (template-
# expanded) JSON that was merged in at install time, recorded in the manifest's
# mergedFiles[] array.
#
# Subtraction rules mirror the merge rules:
# - permissions.allow / permissions.deny (and other arrays, e.g. hook event
#     arrays): remove the entries the partial contributed; keep user entries
# - hooks / enabledPlugins / nested objects: recurse, then drop keys that
#     become empty objects so empty scaffolding does not linger
# - scalar / non-array leaf keys: remove only when the live value still equals
#     the contributed value (a user override is left untouched)
#
# After subtraction, if the file reduces to an empty object ({}), it is removed.
# Returns 0 on success. If the target does not exist, this is a no-op (0).
unmerge_settings() {
  local target="$1"
  local partial="$2"

  _require_jq || return 1

  # Nothing to un-merge from a file that is already gone.
  [ -f "$target" ] || return 0

  if [ ! -f "$partial" ]; then
    echo "WARNING: Recorded partial not found, leaving target untouched: $partial" >&2
    return 0
  fi

  if ! jq empty "$target" 2>/dev/null; then
    echo "ERROR: Invalid JSON in target, refusing to un-merge: $target" >&2
    return 1
  fi
  if ! jq empty "$partial" 2>/dev/null; then
    echo "ERROR: Invalid JSON in recorded partial: $partial" >&2
    return 1
  fi

  local result
  result=$(jq -s '
    # subtract(live; contributed) -> live with contributed removed
    def subtract(a; b):
      a as $a | b as $b |
      if ($a | type) == "object" and ($b | type) == "object" then
        # For every key the contribution touched, subtract it from live.
        reduce ($b | keys[]) as $key ($a;
          if ($a | has($key) | not) then
            .
          elif (($a[$key] | type) == "array") and (($b[$key] | type) == "array") then
            # Remove contributed array entries (by value). Keeps user entries.
            ( ($a[$key]) - ($b[$key]) ) as $remaining
            | if ($remaining | length) == 0 then del(.[$key])
              else .[$key] = $remaining end
          elif (($a[$key] | type) == "object") and (($b[$key] | type) == "object") then
            ( subtract($a[$key]; $b[$key]) ) as $nested
            | if ($nested | length) == 0 then del(.[$key])
              else .[$key] = $nested end
          elif ($a[$key] == $b[$key]) then
            # Identical leaf the contribution provided: remove it.
            del(.[$key])
          else
            # User overrode the value after install: leave it alone.
            .
          end
        )
      else
        $a
      end;
    subtract(.[0]; .[1])
  ' "$target" "$partial" 2>/dev/null)

  if [ -z "$result" ]; then
    echo "ERROR: Un-merge failed for $target - $partial" >&2
    return 1
  fi

  # If the file is now an empty object, the user has nothing left here: remove it.
  if [ "$(echo "$result" | jq -c '.')" = "{}" ]; then
    rm -f "$target"
    return 0
  fi

  echo "$result" | jq '.' > "$target"
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
