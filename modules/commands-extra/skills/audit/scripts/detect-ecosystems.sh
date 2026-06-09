#!/usr/bin/env bash
# detect-ecosystems.sh
# Phase-0 ecosystem detector for /audit (Epic 1.3)
#
# Usage: bash detect-ecosystems.sh [TARGET_DIR]
#   TARGET_DIR defaults to git root (or cwd if not in a git repo)
#
# Output: JSON to stdout:
#   {
#     "detected_ecosystems": [...],
#     "project_shape": {
#       "monorepo_packages": [...],
#       "frameworks": [...],
#       "has_migrations": bool,
#       "has_dockerfile": bool,
#       "has_workflows": bool,
#       "is_extension": bool,
#       "is_mobile": bool
#     },
#     "available_tools": [...]
#   }
#
# BSD-safe: avoids GNU-only Perl-regex grep flags.

set -euo pipefail

# ---------------------------------------------------------------------------
# Pre-flight: require jq
# ---------------------------------------------------------------------------
if ! command -v jq >/dev/null 2>&1; then
  echo "detect-ecosystems.sh: jq is required but not installed" >&2
  exit 1
fi

# ---------------------------------------------------------------------------
# Resolve target directory
# ---------------------------------------------------------------------------
if [ -n "${1:-}" ]; then
  TARGET_DIR="$1"
else
  # Default to git root; fall back to cwd
  TARGET_DIR=$(git rev-parse --show-toplevel 2>/dev/null || pwd)
fi

# Canonicalize (resolve symlinks, strip trailing slash)
TARGET_DIR=$(cd "$TARGET_DIR" && pwd)

# ---------------------------------------------------------------------------
# Ecosystem detection helpers
# ---------------------------------------------------------------------------

# Check file exists under TARGET_DIR
has_file() {
  [ -f "$TARGET_DIR/$1" ]
}

# Check directory exists under TARGET_DIR
has_dir() {
  [ -d "$TARGET_DIR/$1" ]
}

# Find files matching a name pattern under TARGET_DIR (depth-limited)
# Returns non-zero if none found
find_files() {
  local name="$1"
  local maxdepth="${2:-4}"
  find "$TARGET_DIR" -maxdepth "$maxdepth" -name "$name" 2>/dev/null \
    | head -1 | grep -q .
}

# Find files with a given extension (depth-limited)
# Returns non-zero if none found
find_ext() {
  local ext="$1"
  local maxdepth="${2:-4}"
  find "$TARGET_DIR" -maxdepth "$maxdepth" -name "*.$ext" 2>/dev/null \
    | head -1 | grep -q .
}

# ---------------------------------------------------------------------------
# Detected ecosystems
# ---------------------------------------------------------------------------
ecosystems=()

# JavaScript: package.json present
if has_file "package.json"; then
  ecosystems+=("javascript")
fi

# TypeScript: tsconfig.json OR any .ts/.tsx file (additive with JS)
if has_file "tsconfig.json" || find_ext "ts" 4 || find_ext "tsx" 4; then
  ecosystems+=("typescript")
fi

# Go: go.mod present
if has_file "go.mod"; then
  ecosystems+=("go")
fi

# Python: requirements.txt OR pyproject.toml OR setup.py OR setup.cfg
if has_file "requirements.txt" || has_file "pyproject.toml" \
    || has_file "setup.py" || has_file "setup.cfg" \
    || find_files "requirements*.txt" 3; then
  ecosystems+=("python")
fi

# Rust: Cargo.toml
if has_file "Cargo.toml"; then
  ecosystems+=("rust")
fi

# Ruby: Gemfile OR any .gemspec
if has_file "Gemfile" || find_files "*.gemspec" 2; then
  ecosystems+=("ruby")
fi

# SQL: supabase/migrations OR prisma/migrations OR db/migrate OR any .sql file
if has_dir "supabase/migrations" || has_dir "prisma/migrations" \
    || has_dir "db/migrate" || has_dir "db/migrations" \
    || has_dir "database/migrations" \
    || find_ext "sql" 4; then
  ecosystems+=("sql")
fi

# Java: pom.xml OR build.gradle
if has_file "pom.xml" || has_file "build.gradle" || has_file "build.gradle.kts"; then
  ecosystems+=("java")
fi

# Kotlin: any .kt file
if find_ext "kt" 4; then
  ecosystems+=("kotlin")
fi

# Swift: xcodeproj OR xcworkspace OR Package.swift OR any .swift file
if find_files "*.xcodeproj" 3 || find_files "*.xcworkspace" 3 \
    || has_file "Package.swift" || find_ext "swift" 4; then
  ecosystems+=("swift")
fi

# Shell: any .sh file
if find_ext "sh" 4; then
  ecosystems+=("shell")
fi

# Docker: Dockerfile present (shape also captured in has_dockerfile)
if has_file "Dockerfile" || find_files "Dockerfile" 3 \
    || find_files "Dockerfile.*" 3; then
  ecosystems+=("docker")
fi

# Terraform / HCL: any .tf file
if find_ext "tf" 4; then
  ecosystems+=("terraform")
fi

# ---------------------------------------------------------------------------
# Project shape
# ---------------------------------------------------------------------------

# --- monorepo_packages ---
monorepo_packages=()

# npm/yarn/bun workspaces: parse "workspaces" from package.json
if has_file "package.json"; then
  raw_ws=$(python3 - "$TARGET_DIR/package.json" <<'PYEOF'
import json, sys
try:
    with open(sys.argv[1]) as f:
        pkg = json.load(f)
    ws = pkg.get("workspaces", [])
    if isinstance(ws, dict):
        ws = ws.get("packages", [])
    for entry in ws:
        print(entry)
except Exception:
    pass
PYEOF
  ) || true

  if [ -n "${raw_ws:-}" ]; then
    while IFS= read -r pattern; do
      [ -z "$pattern" ] && continue
      # Strip trailing /* or /** to get a base directory
      dir_pattern=$(echo "$pattern" | sed 's|/\*\*$||; s|/\*$||')
      # Expand to concrete child directories
      while IFS= read -r -d $'\0' d; do
        rel="${d#"$TARGET_DIR"/}"
        monorepo_packages+=("$rel")
      done < <(find "$TARGET_DIR/$dir_pattern" -maxdepth 1 -mindepth 1 \
                     -type d -print0 2>/dev/null || true)
    done <<< "$raw_ws"
  fi
fi

# pnpm workspaces: parse packages from pnpm-workspace.yaml
if has_file "pnpm-workspace.yaml"; then
  raw_ws=$(python3 - "$TARGET_DIR/pnpm-workspace.yaml" <<'PYEOF'
import sys
try:
    with open(sys.argv[1]) as f:
        content = f.read()
    in_packages = False
    for line in content.splitlines():
        stripped = line.strip()
        if stripped.startswith("packages:"):
            in_packages = True
            continue
        if in_packages:
            if stripped.startswith("- "):
                val = stripped[2:].strip().strip('"').strip("'")
                print(val)
            elif stripped and not stripped.startswith("#"):
                in_packages = False
except Exception:
    pass
PYEOF
  ) || true

  if [ -n "${raw_ws:-}" ]; then
    while IFS= read -r pattern; do
      [ -z "$pattern" ] && continue
      dir_pattern=$(echo "$pattern" | sed 's|/\*\*$||; s|/\*$||')
      while IFS= read -r -d $'\0' d; do
        rel="${d#"$TARGET_DIR"/}"
        monorepo_packages+=("$rel")
      done < <(find "$TARGET_DIR/$dir_pattern" -maxdepth 1 -mindepth 1 \
                     -type d -print0 2>/dev/null || true)
    done <<< "$raw_ws"
  fi
fi

# --- frameworks ---
frameworks=()

if has_file "package.json"; then
  detected_fws=$(python3 - "$TARGET_DIR/package.json" <<'PYEOF'
import json, sys
try:
    with open(sys.argv[1]) as f:
        pkg = json.load(f)
    deps = {}
    deps.update(pkg.get("dependencies", {}))
    deps.update(pkg.get("devDependencies", {}))

    # (label_to_emit, dep_key_in_package_json)
    fw_map = [
        ("react",     "react"),
        ("next",      "next"),
        ("vue",       "vue"),
        ("nuxt",      "nuxt"),
        ("svelte",    "svelte"),
        ("angular",   "@angular/core"),
        ("remix",     "@remix-run/node"),
        ("astro",     "astro"),
        ("solid",     "solid-js"),
        ("express",   "express"),
        ("fastify",   "fastify"),
        ("hono",      "hono"),
        ("electron",  "electron"),
        ("tauri",     "@tauri-apps/api"),
        ("vite",      "vite"),
        ("webpack",   "webpack"),
        ("turbo",     "turbo"),
    ]
    seen = set()
    for label, dep in fw_map:
        if dep in deps and label not in seen:
            seen.add(label)
            print(label)
except Exception:
    pass
PYEOF
  ) || true

  if [ -n "${detected_fws:-}" ]; then
    while IFS= read -r fw; do
      [ -n "$fw" ] && frameworks+=("$fw")
    done <<< "$detected_fws"
  fi
fi

# Python frameworks (scan requirements.txt)
if [ -f "$TARGET_DIR/requirements.txt" ]; then
  content=$(cat "$TARGET_DIR/requirements.txt")
  for fw in django flask fastapi starlette tornado sanic; do
    if echo "$content" | grep -qi "^[[:space:]]*${fw}[>=<!\[]"; then
      frameworks+=("$fw")
    fi
  done
fi

# Go frameworks (scan go.mod)
if has_file "go.mod"; then
  content=$(cat "$TARGET_DIR/go.mod")
  for fw_path in "gin-gonic/gin" "labstack/echo" "gofiber/fiber" "go-chi/chi"; do
    fw_label="${fw_path##*/}"
    if echo "$content" | grep -q "$fw_path"; then
      frameworks+=("$fw_label")
    fi
  done
fi

# --- has_migrations ---
# TRUE only when a real migration directory exists (not on presence of .sql files)
has_migrations=false
if has_dir "supabase/migrations" || has_dir "prisma/migrations" \
    || has_dir "db/migrate" || has_dir "db/migrations" \
    || has_dir "database/migrations"; then
  has_migrations=true
fi

# --- has_dockerfile ---
has_dockerfile=false
if has_file "Dockerfile" || find_files "Dockerfile" 3 \
    || find_files "Dockerfile.*" 3 \
    || has_file "docker-compose.yml" || has_file "docker-compose.yaml"; then
  has_dockerfile=true
fi

# --- has_workflows ---
has_workflows=false
if has_dir ".github/workflows"; then
  has_workflows=true
fi

# --- is_extension ---
is_extension=false
if has_file "manifest.json"; then
  mv_check=$(python3 - "$TARGET_DIR/manifest.json" <<'PYEOF'
import json, sys
try:
    with open(sys.argv[1]) as f:
        m = json.load(f)
    print("true" if "manifest_version" in m else "false")
except Exception:
    print("false")
PYEOF
  ) || mv_check="false"
  [ "$mv_check" = "true" ] && is_extension=true
fi

# --- is_mobile ---
is_mobile=false
if find_files "*.xcodeproj" 3 || find_files "*.xcworkspace" 3 \
    || has_dir "ios" || has_dir "android" \
    || has_file "Podfile" || has_file "pubspec.yaml"; then
  is_mobile=true
fi

# ---------------------------------------------------------------------------
# Available tools (spine tool list)
# ---------------------------------------------------------------------------
spine_tools=(
  gitleaks
  trufflehog
  semgrep
  trivy
  knip
  eslint
  govulncheck
  gosec
  bandit
  ruff
  pip-audit
  cargo-audit
  clippy
  brakeman
  bundler-audit
  hadolint
  checkov
  actionlint
  zizmor
  pinact
  squawk
  sqlfluff
  npm
  pnpm
  yarn
  bun
  jq
  python3
  node
  go
  cargo
  ruby
  docker
)

available_tools=()
for tool in "${spine_tools[@]}"; do
  if command -v "$tool" >/dev/null 2>&1; then
    available_tools+=("$tool")
  fi
done

# ---------------------------------------------------------------------------
# JSON assembly via jq
# ---------------------------------------------------------------------------

# Build JSON arrays from bash arrays (handle empty arrays portably)
if [ ${#ecosystems[@]} -eq 0 ]; then
  ecosystems_json="[]"
else
  ecosystems_json=$(printf '%s\n' "${ecosystems[@]}" | jq -R . | jq -s .)
fi

if [ ${#monorepo_packages[@]} -eq 0 ]; then
  packages_json="[]"
else
  packages_json=$(printf '%s\n' "${monorepo_packages[@]}" | jq -R . | jq -s .)
fi

if [ ${#frameworks[@]} -eq 0 ]; then
  frameworks_json="[]"
else
  frameworks_json=$(printf '%s\n' "${frameworks[@]}" | jq -R . | jq -s .)
fi

if [ ${#available_tools[@]} -eq 0 ]; then
  tools_json="[]"
else
  tools_json=$(printf '%s\n' "${available_tools[@]}" | jq -R . | jq -s .)
fi

jq -n \
  --argjson ecosystems "$ecosystems_json" \
  --argjson packages   "$packages_json" \
  --argjson frameworks "$frameworks_json" \
  --arg     migrations "$has_migrations" \
  --arg     dockerfile "$has_dockerfile" \
  --arg     workflows  "$has_workflows" \
  --arg     extension  "$is_extension" \
  --arg     mobile     "$is_mobile" \
  --argjson tools      "$tools_json" \
  '{
    detected_ecosystems: $ecosystems,
    project_shape: {
      monorepo_packages: $packages,
      frameworks:        $frameworks,
      has_migrations:    ($migrations == "true"),
      has_dockerfile:    ($dockerfile == "true"),
      has_workflows:     ($workflows  == "true"),
      is_extension:      ($extension  == "true"),
      is_mobile:         ($mobile     == "true")
    },
    available_tools: $tools
  }'
