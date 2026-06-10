#!/usr/bin/env bash
# CCGM audit spine -- deterministic tool runner
#
# Runs each wrapped tool against the target repository, normalizes output
# to finding.schema.json JSONL, and aggregates all findings + coverage-gap
# notes to stdout.
#
# Usage:
#   run.sh [--repo <abs_path>] [--tools <comma_list>] [--output <file>]
#
#   --repo  <path>   Absolute path to the repo root (default: cwd)
#   --tools <list>   Comma-separated subset of tools to run (default: all)
#                    Valid: gitleaks,semgrep,dep-audit,knip,eslint,
#                           govulncheck,bandit,hadolint,actionlint,trivy,
#                           squawk,sqlfluff
#   --output <file>  Write aggregated JSONL to this file instead of stdout
#
# Output: JSONL -- one JSON object per line, either a finding or a note.
# Exit code: always 0 (individual tool failures become coverage-gap notes).
#
# Safety guarantees (ss3.7):
#   - No repo-derived value is interpolated into a shell string.
#     Paths are passed as argv to wrappers; wrappers pass them as argv to tools.
#   - All wrappers are shellcheck-clean.
#   - Config isolation: each wrapper enforces tool-specific isolation flags.
#   - Secret values are redacted (first-4+length) before appearing in output.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------
REPO_ROOT=""
REQUESTED_TOOLS="gitleaks,semgrep,dep-audit,knip,eslint,govulncheck,bandit,hadolint,actionlint,trivy,squawk,sqlfluff"
OUTPUT_FILE=""

# ---------------------------------------------------------------------------
# Argument parsing (no eval, no indirect expansion of user-supplied values)
# ---------------------------------------------------------------------------
while [[ $# -gt 0 ]]; do
  case "$1" in
    --repo)
      REPO_ROOT="$2"
      shift 2
      ;;
    --tools)
      REQUESTED_TOOLS="$2"
      shift 2
      ;;
    --output)
      OUTPUT_FILE="$2"
      shift 2
      ;;
    *)
      printf 'Unknown argument: %s\n' "$1" >&2
      exit 1
      ;;
  esac
done

# Default repo root to current directory
if [[ -z "$REPO_ROOT" ]]; then
  REPO_ROOT="$(pwd)"
fi

# Validate repo root exists (safety: do not run against a path that doesn't exist)
if [[ ! -d "$REPO_ROOT" ]]; then
  printf 'ERROR: repo root does not exist: %s\n' "$REPO_ROOT" >&2
  exit 1
fi

# ---------------------------------------------------------------------------
# Tool registry -- ordered list of (tool_name, wrapper_script) pairs.
# Paths are absolute, never derived from user input.
# ---------------------------------------------------------------------------
declare -A TOOL_WRAPPERS
TOOL_WRAPPERS["gitleaks"]="$SCRIPT_DIR/wrap-gitleaks.sh"
TOOL_WRAPPERS["semgrep"]="$SCRIPT_DIR/wrap-semgrep.sh"
TOOL_WRAPPERS["dep-audit"]="$SCRIPT_DIR/wrap-dep-audit.sh"
TOOL_WRAPPERS["knip"]="$SCRIPT_DIR/wrap-knip.sh"
TOOL_WRAPPERS["eslint"]="$SCRIPT_DIR/wrap-eslint.sh"
TOOL_WRAPPERS["govulncheck"]="$SCRIPT_DIR/wrap-govulncheck.sh"
TOOL_WRAPPERS["bandit"]="$SCRIPT_DIR/wrap-bandit.sh"
TOOL_WRAPPERS["hadolint"]="$SCRIPT_DIR/wrap-hadolint.sh"
TOOL_WRAPPERS["actionlint"]="$SCRIPT_DIR/wrap-actionlint.sh"
TOOL_WRAPPERS["trivy"]="$SCRIPT_DIR/wrap-trivy.sh"
TOOL_WRAPPERS["squawk"]="$SCRIPT_DIR/wrap-squawk.sh"
TOOL_WRAPPERS["sqlfluff"]="$SCRIPT_DIR/wrap-sqlfluff.sh"

# Ordered execution list (stable, deterministic)
TOOL_ORDER=(gitleaks semgrep dep-audit knip eslint govulncheck bandit hadolint actionlint trivy squawk sqlfluff)

# ---------------------------------------------------------------------------
# Parse requested tools into a set (using associative array for O(1) lookup)
# ---------------------------------------------------------------------------
declare -A REQUESTED_SET
IFS=',' read -ra _REQ_TOOLS <<< "$REQUESTED_TOOLS"
for _t in "${_REQ_TOOLS[@]}"; do
  _t="${_t// /}"  # strip spaces
  REQUESTED_SET["$_t"]=1
done

# ---------------------------------------------------------------------------
# Aggregation: collect all output to a temp file if --output is set,
# otherwise stream directly to stdout.
# ---------------------------------------------------------------------------
if [[ -n "$OUTPUT_FILE" ]]; then
  AGTMPFILE="$(mktemp /tmp/ccgm-spine-agg-XXXXXX.jsonl)"
  trap 'rm -f "$AGTMPFILE"' EXIT
  SINK="$AGTMPFILE"
else
  SINK="/dev/stdout"
fi

# ---------------------------------------------------------------------------
# Emit a provenance header record
# Use python3 json.dumps so repo paths / tool names containing ", \, or
# newlines produce valid JSONL instead of malformed output.
# ---------------------------------------------------------------------------
python3 - "$REPO_ROOT" "$REQUESTED_TOOLS" "$(date -u +"%Y-%m-%dT%H:%M:%SZ")" << 'PYEOF' >> "$SINK"
import json, sys
repo, tools, ts = sys.argv[1], sys.argv[2], sys.argv[3]
print(json.dumps({
    "type": "provenance",
    "tool": "ccgm-spine",
    "version": "1.0",
    "repo": repo,
    "tools_requested": tools,
    "timestamp": ts,
}))
PYEOF

# ---------------------------------------------------------------------------
# Run each tool wrapper in order
# ---------------------------------------------------------------------------
for TOOL in "${TOOL_ORDER[@]}"; do
  # Skip tools not in the requested set
  if [[ -z "${REQUESTED_SET[$TOOL]:-}" ]]; then
    continue
  fi

  WRAPPER="${TOOL_WRAPPERS[$TOOL]:-}"
  if [[ -z "$WRAPPER" || ! -f "$WRAPPER" ]]; then
    printf '{"type":"coverage_gap","tool":"%s","check_id":"spine/missing-wrapper","description":"wrapper script not found: %s"}\n' \
      "$TOOL" "$WRAPPER" >> "$SINK"
    continue
  fi

  # Run wrapper -- REPO_ROOT is passed as a positional argv element,
  # never interpolated into a shell string.
  set +e
  bash "$WRAPPER" "$REPO_ROOT" >> "$SINK" 2>/dev/null
  WRAPPER_EXIT=$?
  set -e

  if [[ $WRAPPER_EXIT -ne 0 ]]; then
    printf '{"type":"coverage_gap","tool":"%s","check_id":"spine/wrapper-error","description":"wrapper exited with code %d"}\n' \
      "$TOOL" "$WRAPPER_EXIT" >> "$SINK"
  fi
done

# ---------------------------------------------------------------------------
# If --output was specified, move temp file to destination
# ---------------------------------------------------------------------------
if [[ -n "$OUTPUT_FILE" ]]; then
  cp "$AGTMPFILE" "$OUTPUT_FILE"
  printf 'Spine complete. Findings written to: %s\n' "$OUTPUT_FILE" >&2
fi
