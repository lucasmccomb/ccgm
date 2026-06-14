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
#      was never seen before. To avoid false positives on illustrative
#      placeholders, a line is exempt only if it carries an allow marker or
#      matches a tightly-scoped known-placeholder pattern (see allow_line).
#
# Self-test:  bash tests/test-no-personal-data.sh --self-test
#   Plants a fake token in a temp dir, asserts the detector FAILs on it, and
#   asserts a clean temp file PASSes. Regression-tests the detector itself.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# ---------------------------------------------------------------------------
# Pattern definitions
# ---------------------------------------------------------------------------

# Class 1: maintainer-specific identifiers. Unconditional fail.
# Covers: usernames, personal paths, Supabase project refs, service URLs,
# Tailscale hostnames/IPs, and personal device names.
IDENTITY_PATTERN='lucasmccomb|Lucas McComb|@lucasmccomb|/Users/lem|lem-personal|lem-agent-logs|hyhaowdndehadgcwjxtw|hwoxbllmdqvavxthrlql|eluketronic\.app\.n8n\.cloud|lem-mbp|100\.113\.180\.79|iphone171'

# Class 2: generic secret / PII shapes. Subject to the allow_line exemption.
#   sk-...            OpenAI / Anthropic style keys
#   ghp_ gho_         GitHub personal / OAuth tokens
#   github_pat_       GitHub fine-grained tokens
#   re_...            Resend keys
#   AKIA[16]          AWS access key IDs
#   PRIVATE KEY PEM   private key blocks
#   email addresses   PII
SECRET_PATTERN='sk-[A-Za-z0-9_-]{20,}|ghp_[A-Za-z0-9]{20,}|gho_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|re_[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16}|-----BEGIN [A-Z ]*PRIVATE KEY-----|[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}'

# A matched secret/PII line is EXEMPT if it satisfies any allow rule below.
# This is deliberately narrow: real leaks should not look like placeholders.
allow_line() {
  local line="$1"

  # Explicit opt-out marker for intentional illustrative content.
  case "$line" in
    *ccgm-allow-secret*) return 0 ;;
  esac

  # Documented placeholder / template shapes (never a real value).
  case "$line" in
    *__PLACEHOLDER__*) return 0 ;;
    *'<sk-'*) return 0 ;;       # angle-bracket placeholder, e.g. <sk-ant-...>
    *'<ghp_'*) return 0 ;;
    *'sk-ant-...'*) return 0 ;;
    *'ghp_...'*) return 0 ;;
    *'ghp_xxx'*|*'ghp_XXX'*) return 0 ;;
    *'ghp_newtoken'*) return 0 ;;
  esac

  # Regex-class definitions and redaction docs (the modules whose JOB is to
  # detect secrets describe these shapes literally). These are patterns, not
  # values: the prefix is immediately followed by a regex character class
  # (`[`, `\`) or a quantifier brace (`{`), never by a literal token char.
  if printf '%s' "$line" | grep -qE '(sk-|ghp_|gho_|github_pat_|re_)[A-Za-z0-9]*(\\\[?|\[|\{)[A-Za-z0-9]'; then
    return 0
  fi
  case "$line" in
    *redacted*|*'[redacted'*) return 0 ;;
  esac

  # Well-known public example/fake tokens used in tests & docs.
  case "$line" in
    *AKIAIOSFODNN7EXAMPLE*) return 0 ;;          # AWS official docs example
    *ghp_aaaaaaaaaaaa*) return 0 ;;              # obvious all-a fake
    *ghp_AbcDefGhi*) return 0 ;;                 # obvious sequential fake
    *FakeToken*|*faketoken*) return 0 ;;
    *'ForTesting'*) return 0 ;;
    *'sk-proj-abc123'*) return 0 ;;              # illustrative tos-compliance example
  esac

  # PEM private-key *header lines* with no key body are documentation, not a
  # leak (a real key has base64 material on following lines). Exempt a line
  # that is only the BEGIN header (optionally indented / list-prefixed).
  if printf '%s' "$line" | grep -qE '^[[:space:]]*-?[[:space:]]*-----BEGIN [A-Z ]*PRIVATE KEY-----[[:space:]]*$'; then
    return 0
  fi

  # Example / reserved / test email domains (RFC 2606 + obvious fixtures).
  # Only exempt the line if EVERY email on it is a placeholder domain AND no
  # non-email token shape remains once the emails are stripped out.
  local emails real
  emails=$(printf '%s' "$line" | grep -oE '[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}' || true)
  if [ -n "$emails" ]; then
    # A placeholder email is one whose domain is a reserved/example domain,
    # or a single-letter throwaway fixture like a@b.com / x@y.io.
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

# ---------------------------------------------------------------------------
# Core scan
# ---------------------------------------------------------------------------
# scan_paths <path...>
# Echoes "FILE:LINENO:matched line" for every offending line.
# Returns 0 if clean, 1 if any offenders found.
#
# Usage: scan_paths <mode> <path...>
#   mode=identity  scan only IDENTITY_PATTERN (unconditional fail)
#   mode=secret    scan only SECRET_PATTERN, with allow_line() exemptions
#
# The two modes scan separate surfaces (see callers): the identity scan keeps
# its historical, narrow target set (the public GitHub owner handle appears
# legitimately throughout docs/, Go import paths, FUNDING.yml, and LICENSE, so
# scanning those for the handle would be all false positives). The secret scan
# runs against the whole repo because a NEW secret can land anywhere.
list_text_files() {
  find "$@" -type f \
    \( -name '*.md' -o -name '*.json' -o -name '*.py' -o -name '*.sh' \
       -o -name '*.yml' -o -name '*.yaml' -o -name '*.txt' \) \
    -not -path '*/.git/*' -not -path '*/node_modules/*' \
    -not -path '*/__pycache__/*' -not -path '*/.pytest_cache/*' \
    -not -path '*/docs/audits/*' 2>/dev/null || true
}

scan_paths() {
  local mode="$1"; shift
  local found=0 files f rel
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
      # there but personal paths are not. (Matches the historical behavior of
      # excluding README.md / postInstall.sh from the username check.)
      local idpat="$IDENTITY_PATTERN"
      case "$rel" in
        README.md|*/README.md|postInstall.sh|*/postInstall.sh)
          idpat='/Users/lem|lem-personal|lem-agent-logs|hyhaowdndehadgcwjxtw|hwoxbllmdqvavxthrlql|eluketronic\.app\.n8n\.cloud|lem-mbp|100\.113\.180\.79|iphone171'
          ;;
      esac
      while IFS= read -r hit; do
        [ -z "$hit" ] && continue
        echo "$rel:$hit"
        found=1
      done < <(grep -nE "$idpat" "$f" 2>/dev/null || true)
    else
      while IFS= read -r hit; do
        [ -z "$hit" ] && continue
        local content="${hit#*:}"
        if allow_line "$content"; then
          continue
        fi
        echo "$rel:$hit"
        found=1
      done < <(grep -nE "$SECRET_PATTERN" "$f" 2>/dev/null || true)
    fi
  done <<< "$files"

  return $found
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

  echo "--- planted-token file (expect DETECT) ---"
  if scan_paths secret "$tmp/leak.txt" >/dev/null; then
    echo "  UNEXPECTED PASS: detector missed the planted token"
    rc=1
  else
    echo "  OK: detector flagged the planted token"
  fi

  echo "--- planted-PII-email file (expect DETECT) ---"
  if scan_paths secret "$tmp/pii.txt" >/dev/null; then
    echo "  UNEXPECTED PASS: detector missed the planted PII email"
    rc=1
  else
    echo "  OK: detector flagged the planted PII email"
  fi

  echo "--- clean file (expect PASS) ---"
  if scan_paths secret "$tmp/clean.txt" >/dev/null; then
    echo "  OK: clean file passed"
  else
    echo "  UNEXPECTED FAIL: detector flagged a clean file"
    scan_paths secret "$tmp/clean.txt" || true
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
echo "Scanning whole repo for secret/PII shapes..."
echo ""

set +e
identity_hits=$(scan_paths identity "${identity_targets[@]}")
id_rc=$?
# Secret scan: widened to the whole repo (docs/ included), minus .git,
# node_modules, caches, and local-only audit artifacts.
secret_hits=$(scan_paths secret "$REPO_ROOT")
sec_rc=$?
set -e

offenders=""
[ -n "$identity_hits" ] && offenders="$identity_hits"
[ -n "$secret_hits" ] && offenders="${offenders:+$offenders
}$secret_hits"

rc=0
{ [ "$id_rc" -ne 0 ] || [ "$sec_rc" -ne 0 ]; } && rc=1

if [ "$rc" -ne 0 ]; then
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
