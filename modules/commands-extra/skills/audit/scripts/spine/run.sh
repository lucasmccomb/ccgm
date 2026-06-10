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
#                           zizmor,pinact,squawk,sqlfluff,checkov,
#                           pip-audit,cargo-audit,bundler-audit
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
REQUESTED_TOOLS="gitleaks,semgrep,dep-audit,knip,eslint,govulncheck,bandit,hadolint,actionlint,trivy,zizmor,pinact,squawk,sqlfluff,checkov,pip-audit,cargo-audit,bundler-audit"
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
# Bash-3.2-portable: case dispatch instead of associative array
# (declare -A requires bash 4+).
# ---------------------------------------------------------------------------

# Ordered execution list (stable, deterministic)
TOOL_ORDER=(gitleaks semgrep dep-audit knip eslint govulncheck bandit hadolint actionlint trivy zizmor pinact squawk sqlfluff checkov pip-audit cargo-audit bundler-audit)

# Resolve wrapper path for a given tool name.
# Sets WRAPPER to the script path, or empty string if unknown.
_get_wrapper() {
  local _tool="$1"
  case "$_tool" in
    gitleaks)       WRAPPER="$SCRIPT_DIR/wrap-gitleaks.sh" ;;
    semgrep)        WRAPPER="$SCRIPT_DIR/wrap-semgrep.sh" ;;
    dep-audit)      WRAPPER="$SCRIPT_DIR/wrap-dep-audit.sh" ;;
    knip)           WRAPPER="$SCRIPT_DIR/wrap-knip.sh" ;;
    eslint)         WRAPPER="$SCRIPT_DIR/wrap-eslint.sh" ;;
    govulncheck)    WRAPPER="$SCRIPT_DIR/wrap-govulncheck.sh" ;;
    bandit)         WRAPPER="$SCRIPT_DIR/wrap-bandit.sh" ;;
    hadolint)       WRAPPER="$SCRIPT_DIR/wrap-hadolint.sh" ;;
    actionlint)     WRAPPER="$SCRIPT_DIR/wrap-actionlint.sh" ;;
    trivy)          WRAPPER="$SCRIPT_DIR/wrap-trivy.sh" ;;
    zizmor)         WRAPPER="$SCRIPT_DIR/wrap-zizmor.sh" ;;
    pinact)         WRAPPER="$SCRIPT_DIR/wrap-pinact.sh" ;;
    squawk)         WRAPPER="$SCRIPT_DIR/wrap-squawk.sh" ;;
    sqlfluff)       WRAPPER="$SCRIPT_DIR/wrap-sqlfluff.sh" ;;
    checkov)        WRAPPER="$SCRIPT_DIR/wrap-checkov.sh" ;;
    pip-audit)      WRAPPER="$SCRIPT_DIR/wrap-pip-audit.sh" ;;
    cargo-audit)    WRAPPER="$SCRIPT_DIR/wrap-cargo-audit.sh" ;;
    bundler-audit)  WRAPPER="$SCRIPT_DIR/wrap-bundler-audit.sh" ;;
    *)              WRAPPER="" ;;
  esac
}

# ---------------------------------------------------------------------------
# Parse requested tools into a colon-delimited string for membership testing.
# Bash-3.2-portable: no associative arrays (declare -A requires bash 4+).
# Membership test pattern: case ":$_REQUESTED_CSV_NORM:" in *":$TOOL:"*) ...
# ---------------------------------------------------------------------------
_REQUESTED_CSV_NORM=""
IFS=',' read -ra _REQ_TOOLS <<< "$REQUESTED_TOOLS"
for _t in "${_REQ_TOOLS[@]}"; do
  _t="${_t// /}"  # strip spaces
  _REQUESTED_CSV_NORM="${_REQUESTED_CSV_NORM}:${_t}"
done
_REQUESTED_CSV_NORM="${_REQUESTED_CSV_NORM}:"  # trailing colon for uniform matching

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
  # Bash-3.2-portable membership test via case pattern on colon-delimited string.
  # _REQUESTED_CSV_NORM has the form ":tool1:tool2:...:toolN:" (leading+trailing colon).
  case "${_REQUESTED_CSV_NORM}" in
    *":${TOOL}:"*) ;;  # present -- fall through
    *) continue ;;     # not requested -- skip
  esac

  _get_wrapper "$TOOL"
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
