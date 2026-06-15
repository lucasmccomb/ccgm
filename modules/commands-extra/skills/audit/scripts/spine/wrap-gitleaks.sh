#!/usr/bin/env bash
# CCGM audit spine -- gitleaks wrapper
# Detects hard-coded secrets in the working tree (default) or full git history.
#
# Usage: wrap-gitleaks.sh <repo_root>
#   repo_root: absolute path to the repository root
#
# Scan modes:
#   Working-tree (default):
#     Uses `gitleaks detect --no-git` -- scans files present in the working
#     directory. Works in worktrees and detached-HEAD states.
#
#   History (opt-in):
#     Set CCGM_GITLEAKS_HISTORY=1 before invoking to use `gitleaks git`
#     instead. Walks every commit in the full git history -- finds secrets
#     that were committed and later removed. Requires a real git repo with
#     at least one commit. No network calls are made.
#
# --verify-secrets (opt-in, NOT wired by default):
#   Live verification of detected secrets by calling credential-issuer APIs
#   is intentionally out of scope for the default path; it makes network calls
#   to external services and triggers security-review gate C1. To add opt-in
#   verification, set CCGM_GITLEAKS_VERIFY=1 only after obtaining approval.
#   The trufflehog wrapper (currently not installed) provides this capability
#   as an independent optional step; do not rely on it being present.
#
# Output (stdout): JSONL -- one JSON object per line.
# Exit code: always 0

set -euo pipefail

REPO_ROOT="${1:-}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
NORMALIZE_PY="$SCRIPT_DIR/normalize.py"
PARSE_PY="$SCRIPT_DIR/parse-gitleaks.py"

if [[ -z "$REPO_ROOT" ]]; then
  python3 "$NORMALIZE_PY" --emit-skip gitleaks \
    "secrets/leaked-credential:no repo_root argument supplied"
  exit 0
fi

if ! command -v gitleaks > /dev/null 2>&1; then
  python3 "$NORMALIZE_PY" --emit-skip gitleaks \
    "secrets/leaked-credential:gitleaks not installed -- secret scanning skipped" \
    "secrets/high-entropy-string:gitleaks not installed -- entropy scan skipped"
  exit 0
fi

TMPFILE="$(mktemp /tmp/ccgm-gitleaks-XXXXXX.json)"
CONFIGFILE="$(mktemp /tmp/ccgm-gitleaks-cfg-XXXXXX.toml)"
trap 'rm -f "$TMPFILE" "$CONFIGFILE"' EXIT

# Path exclusion (field report #1): `--no-git` walks the whole filesystem with
# NO path exclusions, so it scans a 566 MB node_modules and every stale
# worktree copy -- 22+ minutes on this tool alone.  gitleaks excludes nothing
# without a config.  We generate a config that keeps the default ruleset
# ([extend] useDefault = true) and allowlists every canonical excluded dir;
# this dropped gitleaks from 22 min -> 34 s.
#
# Passing REPO_ROOT also allowlists GITIGNORED paths: a working-tree scan would
# otherwise report a gitignored, never-committed .env.local as a CRITICAL
# leaked-credential. A leaked credential describes committed/tracked content,
# so gitignored local files must not be flagged (field report #726).
python3 "$SCRIPT_DIR/exclude.py" --gitleaks-config "$CONFIGFILE" "$REPO_ROOT" 2>/dev/null || true

# Determine scan mode: history or working-tree
HISTORY_MODE="${CCGM_GITLEAKS_HISTORY:-0}"

set +e
if [[ "$HISTORY_MODE" == "1" ]]; then
  # Full-history scan: walks every commit in the repository.
  # Uses `gitleaks git` which requires a real git repo.
  # --no-banner: suppress the gitleaks ASCII banner (keeps output clean)
  gitleaks git \
    --config "$CONFIGFILE" \
    --report-format json \
    --report-path "$TMPFILE" \
    --exit-code 0 \
    --no-banner \
    "$REPO_ROOT" \
    > /dev/null 2>&1
else
  # Working-tree scan (default): scans files present in the working directory.
  # --no-git: works in worktrees / detached heads
  gitleaks detect \
    --config "$CONFIGFILE" \
    --source "$REPO_ROOT" \
    --report-format json \
    --report-path "$TMPFILE" \
    --no-git \
    --exit-code 0 \
    > /dev/null 2>&1
fi
GL_EXIT=$?
set -e

if [[ $GL_EXIT -ne 0 && ! -s "$TMPFILE" ]]; then
  python3 "$NORMALIZE_PY" --emit-skip gitleaks \
    "secrets/leaked-credential:gitleaks exited non-zero with no output"
  exit 0
fi

# Normalize output -> finding.schema.json
python3 "$PARSE_PY" "$TMPFILE" "$REPO_ROOT"
