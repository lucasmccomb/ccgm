#!/usr/bin/env bash
set -euo pipefail

# CCGM Personal Data Check
# Ensures no personal/private data or live secrets leaked into the public repo.
#
# Two classes of detection:
#   1. Maintainer-specific identifiers (names, paths, project refs, hostnames).
#      These are unconditional failures.
#   2. Generic secret/PII *shapes* (API keys, tokens, private keys, emails).
#      A NEW secret pasted by any contributor trips these even if the value
#      was never seen before.
#
# Design (deliberately robust-by-construction, not heuristic):
#   * OFFENDERS ARE THE SINGLE SOURCE OF TRUTH. The script builds one offender
#     list (file:line:content) and the exit decision is purely whether that
#     list is non-empty. It is therefore IMPOSSIBLE to FAIL with blank
#     offenders -- any future CI failure is self-diagnosing.
#   * The Class-2 secret scan EXCLUDES known test/fixture/secret-documentation
#     locations by path (tests/, fixtures/, and the audit skill, whose whole
#     job is to document secret shapes). It does NOT try to tell a fake token
#     from a real one per-token -- that heuristic diverged across grep/locale
#     environments. A real secret pasted into actual module/installer/doc
#     content still trips it; legitimate fixtures never do.
#   * A handful of explicit, narrow exemptions remain for the rare in-scope
#     placeholder: the `ccgm-allow-secret` line marker, `__PLACEHOLDER__`, and
#     reserved/example email domains (RFC 2606 + ccgm.local / github.com).
#
# Self-test:  bash tests/test-no-personal-data.sh --self-test
#   Plants a fake token in a temp dir, asserts the detector FAILs on it, and
#   asserts a clean temp file PASSes. Regression-tests the detector itself.

# Deterministic byte semantics for grep/sed across GNU and BSD environments.
export LC_ALL=C

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# ---------------------------------------------------------------------------
# Pattern definitions
# ---------------------------------------------------------------------------

# Class 1: maintainer-specific identifiers. Unconditional fail.
# Covers: usernames, personal paths, Supabase project refs, service URLs,
# Tailscale hostnames/IPs, and personal device names.
IDENTITY_PATTERN='lucasmccomb|Lucas McComb|@lucasmccomb|/Users/lem|lem-personal|lem-agent-logs|hyhaowdndehadgcwjxtw|hwoxbllmdqvavxthrlql|eluketronic\.app\.n8n\.cloud|lem-mbp|100\.113\.180\.79|iphone171'

# Class 2: generic secret / PII shapes.
#   sk-...            OpenAI / Anthropic style keys
#   ghp_ gho_         GitHub personal / OAuth tokens
#   github_pat_       GitHub fine-grained tokens
#   re_...            Resend keys
#   AKIA[16]          AWS access key IDs
#   PRIVATE KEY PEM   private key blocks
#   email addresses   PII
SECRET_PATTERN='sk-[A-Za-z0-9_-]{20,}|ghp_[A-Za-z0-9]{20,}|gho_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|re_[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16}|-----BEGIN [A-Z ]*PRIVATE KEY-----|[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}'

# A matched secret/PII line is EXEMPT only if it satisfies one of these narrow
# rules. Intentionally minimal: exclusion-by-location (see scan_paths) handles
# the bulk; this covers the rare in-scope placeholder.
allow_line() {
  local line="$1"

  # Explicit opt-out marker for intentional illustrative content.
  case "$line" in
    *ccgm-allow-secret*) return 0 ;;
    *__PLACEHOLDER__*)   return 0 ;;
  esac

  # Example / reserved / test email domains (RFC 2606 + ccgm.local + the public
  # github.com host that appears in git clone URLs). Only exempt the line if it
  # matched solely on email(s), every email is a placeholder domain, and no
  # other (non-email) token shape remains once the emails are stripped out.
  local emails real
  emails=$(printf '%s' "$line" | grep -oE '[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}' || true)
  if [ -n "$emails" ]; then
    real=$(printf '%s\n' "$emails" \
      | grep -vE '@(example\.(com|org|net)|test|invalid|.*\.test|.*\.invalid|.*\.example|ccgm\.(local|test)|github\.com|.*\.example\.com)$' \
      | grep -vE '^[A-Za-z]@[A-Za-z]\.[A-Za-z]{2,4}$' \
      || true)
    if [ -z "$real" ]; then
      local stripped
      stripped=$(printf '%s' "$line" | sed -E 's/[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}//g')
      if printf '%s' "$stripped" | grep -qE "$SECRET_PATTERN"; then
        return 1   # leftover token shape present; do not exempt
      fi
      return 0
    fi
    return 1   # a real-looking email is present
  fi

  return 1
}

# Class-2 location exclusions: directories whose contents legitimately contain
# secret/PII *shapes* by design. Test and fixture trees plant fake tokens to
# exercise tooling, and the audit skill is itself secret-detection
# documentation (its packs/fixtures describe and embed these shapes literally).
# Excluding these by location is robust: it does not depend on telling a fake
# token from a real one, only on where the file lives.
secret_path_excluded() {
  case "$1" in
    tests/*|*/tests/*)                            return 0 ;;
    fixtures/*|*/fixtures/*)                       return 0 ;;
    modules/commands-extra/skills/audit/*)        return 0 ;;
  esac
  return 1
}

# ---------------------------------------------------------------------------
# Core scan
# ---------------------------------------------------------------------------
# scan_paths <mode> <path...>
#   mode=identity  scan only IDENTITY_PATTERN (unconditional fail)
#   mode=secret    scan only SECRET_PATTERN, with location + allow_line exemptions
#
# Echoes "rel/path:LINENO:matched line" for every offending line, one per line.
# Carries NO meaning in its return code -- callers decide pass/fail purely from
# whether the captured offender text is empty.
list_text_files() {
  find "$@" -type f \
    \( -name '*.md' -o -name '*.json' -o -name '*.py' -o -name '*.sh' \
       -o -name '*.yml' -o -name '*.yaml' -o -name '*.txt' \) \
    -not -path '*/.git/*' -not -path '*/node_modules/*' \
    -not -path '*/__pycache__/*' -not -path '*/.pytest_cache/*' \
    -not -path '*/docs/audits/*' -not -path '*/.claude/*' 2>/dev/null || true
}

scan_paths() {
  local mode="$1"; shift
  local files f rel
  files=$(list_text_files "$@")

  while IFS= read -r f; do
    [ -z "$f" ] && continue
    rel="${f#"$REPO_ROOT"/}"

    # This script defines the identity/secret patterns literally; never flag it.
    case "$rel" in
      tests/test-no-personal-data.sh) continue ;;
    esac

    if [ "$mode" = "identity" ]; then
      # Any README.md and postInstall.sh legitimately hold the clone URL
      # (owner handle) and install commands, so the bare username is allowed
      # there but personal paths are not.
      local idpat="$IDENTITY_PATTERN"
      case "$rel" in
        README.md|*/README.md|postInstall.sh|*/postInstall.sh)
          idpat='/Users/lem|lem-personal|lem-agent-logs|hyhaowdndehadgcwjxtw|hwoxbllmdqvavxthrlql|eluketronic\.app\.n8n\.cloud|lem-mbp|100\.113\.180\.79|iphone171'
          ;;
      esac
      while IFS= read -r hit; do
        [ -z "$hit" ] && continue
        echo "$rel:$hit"
      done < <(grep -nE "$idpat" "$f" 2>/dev/null || true)
    else
      # Secret scan: skip files in test/fixture/secret-doc locations wholesale.
      secret_path_excluded "$rel" && continue
      while IFS= read -r hit; do
        [ -z "$hit" ] && continue
        local content="${hit#*:}"
        if allow_line "$content"; then
          continue
        fi
        echo "$rel:$hit"
      done < <(grep -nE "$SECRET_PATTERN" "$f" 2>/dev/null || true)
    fi
  done <<< "$files"
}

# ---------------------------------------------------------------------------
# Self-test mode
# ---------------------------------------------------------------------------
run_self_test() {
  echo "=== Personal Data Check: detector self-test ==="
  local rc=0
  SELFTEST_TMP=$(mktemp -d)
  local tmp="$SELFTEST_TMP"
  trap 'rm -rf "${SELFTEST_TMP:-}"' EXIT

  # Planted secret: a clearly-fake but real-SHAPED token (not on any allowlist).
  # Built at runtime so the literal never sits in the repo.
  printf 'token=ghp_%s\n' "0bAdC0ffeeDeadBeef0123456789abcdefZZ" > "$tmp/leak.txt"
  # Clean file: only a placeholder email + a templated key.
  printf 'contact=user@example.com\nkey=__PLACEHOLDER__\n' > "$tmp/clean.txt"
  # A second leak: a non-placeholder email (PII).
  printf 'reply-to=jane.contributor@gmail.com\n' > "$tmp/pii.txt"

  local hits
  echo "--- planted-token file (expect DETECT) ---"
  hits=$(scan_paths secret "$tmp/leak.txt")
  if [ -n "$hits" ]; then
    echo "  OK: detector flagged the planted token"
  else
    echo "  UNEXPECTED PASS: detector missed the planted token"
    rc=1
  fi

  echo "--- planted-PII-email file (expect DETECT) ---"
  hits=$(scan_paths secret "$tmp/pii.txt")
  if [ -n "$hits" ]; then
    echo "  OK: detector flagged the planted PII email"
  else
    echo "  UNEXPECTED PASS: detector missed the planted PII email"
    rc=1
  fi

  echo "--- clean file (expect PASS) ---"
  hits=$(scan_paths secret "$tmp/clean.txt")
  if [ -z "$hits" ]; then
    echo "  OK: clean file passed"
  else
    echo "  UNEXPECTED FAIL: detector flagged a clean file"
    echo "$hits" | sed 's/^/    /'
    rc=1
  fi

  echo ""
  if [ "$rc" -eq 0 ]; then
    echo "SELF-TEST PASS"
  else
    echo "SELF-TEST FAIL"
  fi
  return $rc
}

# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
if [ "${1:-}" = "--self-test" ]; then
  run_self_test
  exit $?
fi

echo "=== CCGM Personal Data Check ==="
echo ""

# Identity scan: narrow, historical target set. The public GitHub owner handle
# appears legitimately throughout docs/, Go imports, FUNDING.yml, and LICENSE,
# so the identity scan stays scoped to module/installer content where a generic
# placeholder is expected instead.
IDENTITY_TARGETS=(
  "$REPO_ROOT/modules"
  "$REPO_ROOT/lib"
  "$REPO_ROOT/presets"
  "$REPO_ROOT/start.sh"
  "$REPO_ROOT/update.sh"
  "$REPO_ROOT/uninstall.sh"
  "$REPO_ROOT/README.md"
  "$REPO_ROOT/CONTRIBUTING.md"
  "$REPO_ROOT/CLAUDE.md"
)
identity_targets=()
for t in "${IDENTITY_TARGETS[@]}"; do
  [ -e "$t" ] && identity_targets+=("$t")
done

echo "Scanning for maintainer-specific identifiers (${#identity_targets[@]} targets)..."
echo "Scanning whole repo for secret/PII shapes (test/fixture/audit dirs excluded)..."
echo ""

# Offenders are the single source of truth. Build the combined list; the exit
# decision below keys off whether it is empty, never off a separate return code.
identity_hits=$(scan_paths identity "${identity_targets[@]}")
secret_hits=$(scan_paths secret "$REPO_ROOT")

offenders=""
[ -n "$identity_hits" ] && offenders="$identity_hits"
[ -n "$secret_hits" ] && offenders="${offenders:+$offenders
}$secret_hits"

if [ -n "$offenders" ]; then
  echo "FAIL: Personal data or secret/PII shapes found:"
  echo ""
  echo "$offenders" | head -50 | while IFS= read -r line; do
    echo "  $line"
  done
  echo ""
  echo "Remove all personal data and secrets before committing."
  echo "If a match is an intentional placeholder, add the marker 'ccgm-allow-secret'"
  echo "to that line or use an example.com / __PLACEHOLDER__ shape."
  exit 1
else
  echo "PASS: No personal data or secret/PII shapes found"
  exit 0
fi
