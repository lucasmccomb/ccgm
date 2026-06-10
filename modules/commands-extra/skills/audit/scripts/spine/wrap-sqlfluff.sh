#!/usr/bin/env bash
# CCGM audit spine -- sqlfluff wrapper
# Lints SQL migration files using sqlfluff for style, formatting, and
# dangerous pattern detection (e.g. SECURITY DEFINER).
#
# Usage: wrap-sqlfluff.sh <repo_root>
#
# Output (stdout): JSONL
# Exit code: always 0
#
# sqlfluff lint --format json output shape:
#   [
#     {
#       "filepath": "db/migrations/0001_create_users.sql",
#       "violations": [
#         {
#           "start_line_no": 5,
#           "start_line_pos": 1,
#           "end_line_no": 5,
#           "end_line_pos": 40,
#           "description": "Found SECURITY DEFINER in function definition.",
#           "name": "ST07",
#           "warning": false,
#           "fixable": false
#         }
#       ]
#     }
#   ]
#
# The top-level array has one entry per file. Each entry has a "violations" array.
# Each violation has:
#   - start_line_no:  integer (1-based)
#   - start_line_pos: integer (1-based)
#   - description:    string
#   - name:           string rule code, e.g. "LT01", "ST07"
#   - warning:        bool
#   - fixable:        bool
#
# sqlfluff rule -> check_id mapping (in parse-sqlfluff.py):
#   (all violations)  -> dm/security-definer-function when description matches SECURITY DEFINER
#   (all others)      -> dm/sqlfluff-violation (generic)

set -euo pipefail

REPO_ROOT="${1:-}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
NORMALIZE_PY="$SCRIPT_DIR/normalize.py"
PARSE_PY="$SCRIPT_DIR/parse-sqlfluff.py"

if [[ -z "$REPO_ROOT" ]]; then
  python3 "$NORMALIZE_PY" --emit-skip sqlfluff \
    "dm/security-definer-function:sqlfluff not installed -- SECURITY DEFINER check skipped (llm fallback available)"
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
  python3 "$NORMALIZE_PY" --emit-skip sqlfluff \
    "dm/security-definer-function:no migration directories found -- sqlfluff skipped"
  exit 0
fi

if ! command -v sqlfluff > /dev/null 2>&1; then
  python3 "$NORMALIZE_PY" --emit-skip sqlfluff \
    "dm/security-definer-function:sqlfluff not installed -- SECURITY DEFINER check skipped (llm fallback available)"
  exit 0
fi

# Collect .sql files from migration directories using a NUL-delimited read loop.
# Bash-3.2-portable: mapfile -d '' requires bash 4+; use while-read instead.
SQL_FILES=()
while IFS= read -r -d '' f; do
  SQL_FILES+=("$f")
done < <(
  for dir in "${MIGRATION_DIRS[@]}"; do
    find "$dir" \
      -type f \
      -name "*.sql" \
      -not -path "*/.git/*" \
      -print0
  done
)

if [[ ${#SQL_FILES[@]} -eq 0 ]]; then
  python3 "$NORMALIZE_PY" --emit-skip sqlfluff \
    "dm/security-definer-function:no .sql files found in migration dirs -- sqlfluff skipped"
  exit 0
fi

TMPFILE="$(mktemp /tmp/ccgm-sqlfluff-XXXXXX.json)"
trap 'rm -f "$TMPFILE"' EXIT

# Run sqlfluff lint with JSON format and no project config (--config /dev/null
# is not supported; use --nocolor and rely on --format json for isolation).
# Paths are passed as separate argv elements (injection-safe).
# sqlfluff exits non-zero when violations are found -- ignore exit code.
set +e
sqlfluff lint --format json --nocolor "${SQL_FILES[@]}" > "$TMPFILE" 2>/dev/null || true
set -e

if [[ ! -s "$TMPFILE" ]]; then
  exit 0
fi

python3 "$PARSE_PY" "$TMPFILE" "$REPO_ROOT"
