#!/usr/bin/env bash
# CCGM audit spine -- squawk wrapper
# Lints PostgreSQL migration files for dangerous patterns (missing CONCURRENTLY,
# unquoted reserved keywords, etc.).
#
# Usage: wrap-squawk.sh <repo_root>
#
# Output (stdout): JSONL
# Exit code: always 0
#
# squawk JSON output shape (squawk --reporter json <files>):
#   [
#     {
#       "file": "db/migrations/0001_create_users.sql",
#       "violations": [
#         {
#           "rule": "require-concurrent-index-creation",
#           "level": "Warning",
#           "messages": [
#             {
#               "Note": "..."
#             }
#           ],
#           "position": {
#             "start": { "line": 5, "col": 1 },
#             "end":   { "line": 5, "col": 40 }
#           }
#         }
#       ]
#     }
#   ]
#
# squawk rule -> check_id mapping (in parse-squawk.py):
#   require-concurrent-index-creation -> dm/index-without-concurrently
#   (all others)                      -> dm/squawk-violation (generic)

set -euo pipefail

REPO_ROOT="${1:-}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
NORMALIZE_PY="$SCRIPT_DIR/normalize.py"
PARSE_PY="$SCRIPT_DIR/parse-squawk.py"

if [[ -z "$REPO_ROOT" ]]; then
  python3 "$NORMALIZE_PY" --emit-skip squawk \
    "dm/index-without-concurrently:squawk not installed -- index-without-CONCURRENTLY check skipped" \
    "dm/unquoted-reserved-keyword:squawk not installed -- reserved-keyword check skipped (grep/llm fallback available)"
  exit 0
fi

# Locate migration directories (mirrors detect-ecosystems.sh has_migrations logic)
MIGRATION_DIRS=()
for candidate in \
    "supabase/migrations" \
    "prisma/migrations" \
    "db/migrate" \
    "db/migrations" \
    "database/migrations"; do
  if [[ -d "$REPO_ROOT/$candidate" ]]; then
    MIGRATION_DIRS+=("$REPO_ROOT/$candidate")
  fi
done

if [[ ${#MIGRATION_DIRS[@]} -eq 0 ]]; then
  python3 "$NORMALIZE_PY" --emit-skip squawk \
    "dm/index-without-concurrently:no migration directories found -- squawk skipped" \
    "dm/unquoted-reserved-keyword:no migration directories found -- squawk skipped"
  exit 0
fi

if ! command -v squawk > /dev/null 2>&1; then
  python3 "$NORMALIZE_PY" --emit-skip squawk \
    "dm/index-without-concurrently:squawk not installed -- index-without-CONCURRENTLY check skipped" \
    "dm/unquoted-reserved-keyword:squawk not installed -- reserved-keyword check skipped (grep/llm fallback available)"
  exit 0
fi

# Collect .sql files from migration directories using find + null-delimited output
mapfile -d '' SQL_FILES < <(
  for dir in "${MIGRATION_DIRS[@]}"; do
    find "$dir" \
      -type f \
      -name "*.sql" \
      -not -path "*/.git/*" \
      -print0
  done
)

if [[ ${#SQL_FILES[@]} -eq 0 ]]; then
  python3 "$NORMALIZE_PY" --emit-skip squawk \
    "dm/index-without-concurrently:no .sql files found in migration dirs -- squawk skipped" \
    "dm/unquoted-reserved-keyword:no .sql files found in migration dirs -- squawk skipped"
  exit 0
fi

TMPFILE="$(mktemp /tmp/ccgm-squawk-XXXXXX.json)"
trap 'rm -f "$TMPFILE"' EXIT

# Run squawk: each SQL file is passed as a separate argv element (injection-safe)
set +e
squawk --reporter json "${SQL_FILES[@]}" > "$TMPFILE" 2>/dev/null || true
set -e

if [[ ! -s "$TMPFILE" ]]; then
  exit 0
fi

python3 "$PARSE_PY" "$TMPFILE" "$REPO_ROOT"
