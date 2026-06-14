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
#   * OFFENDERS ARE THE SINGLE SOURCE OF TRUTH. The scanner builds one offender
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
# Why Python, not grep:
#   The previous implementation scanned with BSD/GNU `grep -E`. The large ERE
#   alternation in the secret pattern segfaulted (SIGSEGV / exit 139) on the
#   macOS BSD grep build under CI when scanning the whole repo. Python's `re`
#   engine is already a CI dependency (the suite runs python tests), does not
#   segfault on this pattern, and behaves identically across Linux and macOS.
#   The scanning engine therefore lives in an inline python3 heredoc; this bash
#   file is a thin wrapper preserving the original interface and PASS/FAIL
#   contract so the workflow needs no change.
#
# Self-test:  bash tests/test-no-personal-data.sh --self-test
#   Plants a fake token in a temp dir, asserts the detector FAILs on it, and
#   asserts a clean temp file PASSes. Regression-tests the detector itself.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

PYTHON="${PYTHON:-python3}"

# The scanning engine. Reads a mode + paths on argv and prints offenders
# (file:line:content) to stdout, one per line. Carries no meaning in its exit
# code; callers decide pass/fail purely from whether stdout is empty. The
# REPO_ROOT env var anchors relative-path computation.
#
# Invocation:
#   run_scanner identity <target> [<target> ...]   -> identity offenders
#   run_scanner secret   <root>                    -> secret/PII offenders
run_scanner() {
  "$PYTHON" - "$@" <<'PY'
import os
import re
import sys

REPO_ROOT = os.environ["REPO_ROOT"]

# Class 1: maintainer-specific identifiers. Unconditional fail.
# Covers: usernames, personal paths, Supabase project refs, service URLs,
# Tailscale hostnames/IPs, and personal device names.
IDENTITY_PATTERN = (
    r"lucasmccomb|Lucas McComb|@lucasmccomb|/Users/lem|lem-personal|"
    r"lem-agent-logs|hyhaowdndehadgcwjxtw|hwoxbllmdqvavxthrlql|"
    r"eluketronic\.app\.n8n\.cloud|lem-mbp|100\.113\.180\.79|iphone171"
)

# README.md / postInstall.sh legitimately hold the clone URL (owner handle) and
# install commands, so the bare username is allowed there but personal paths are
# not.
IDENTITY_PATTERN_RELAXED = (
    r"/Users/lem|lem-personal|lem-agent-logs|hyhaowdndehadgcwjxtw|"
    r"hwoxbllmdqvavxthrlql|eluketronic\.app\.n8n\.cloud|lem-mbp|"
    r"100\.113\.180\.79|iphone171"
)

# Class 2: generic secret / PII shapes.
#   sk-...            OpenAI / Anthropic style keys
#   ghp_ gho_         GitHub personal / OAuth tokens
#   github_pat_       GitHub fine-grained tokens
#   re_...            Resend keys
#   AKIA[16]          AWS access key IDs
#   PRIVATE KEY PEM   private key blocks
#   email addresses   PII
SECRET_PATTERN = (
    r"sk-[A-Za-z0-9_-]{20,}|ghp_[A-Za-z0-9]{20,}|gho_[A-Za-z0-9]{20,}|"
    r"github_pat_[A-Za-z0-9_]{20,}|re_[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16}|"
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----|"
    r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"
)

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
# Placeholder / reserved email domains (RFC 2606 + ccgm.local + the public
# github.com host that appears in git clone URLs).
PLACEHOLDER_EMAIL_RE = re.compile(
    r"@(example\.(com|org|net)|test|invalid|.*\.test|.*\.invalid|.*\.example|"
    r"ccgm\.(local|test)|github\.com|.*\.example\.com)$"
)
# Single-letter synthetic placeholder emails like a@b.com.
TRIVIAL_EMAIL_RE = re.compile(r"^[A-Za-z]@[A-Za-z]\.[A-Za-z]{2,4}$")

identity_re = re.compile(IDENTITY_PATTERN)
identity_relaxed_re = re.compile(IDENTITY_PATTERN_RELAXED)
secret_re = re.compile(SECRET_PATTERN)

TEXT_EXTS = (".md", ".json", ".py", ".sh", ".yml", ".yaml", ".txt")

# Directories pruned from the whole-tree walk for ALL scans.
PRUNE_DIRS = {
    ".git",
    "node_modules",
    "__pycache__",
    ".pytest_cache",
    ".claude",
}


def is_text_file(path):
    return path.endswith(TEXT_EXTS)


def relpath(path):
    rp = os.path.relpath(path, REPO_ROOT)
    return rp.replace(os.sep, "/")


def walk_text_files(root):
    """Yield text files under root, pruning PRUNE_DIRS and docs/audits."""
    if os.path.isfile(root):
        if is_text_file(root):
            yield root
        return
    for dirpath, dirnames, filenames in os.walk(root):
        # Prune unwanted directories in place.
        dirnames[:] = [d for d in dirnames if d not in PRUNE_DIRS]
        rel_dir = relpath(dirpath)
        # docs/audits is excluded for every scan.
        if rel_dir == "docs/audits" or rel_dir.endswith("/docs/audits"):
            dirnames[:] = []
            continue
        for name in filenames:
            full = os.path.join(dirpath, name)
            if is_text_file(full):
                yield full


def read_lines(path):
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            return fh.readlines()
    except OSError:
        return []


def secret_path_excluded(rel):
    """Class-2 location exclusions: dirs that legitimately hold secret shapes."""
    parts = rel.split("/")
    if "tests" in parts:
        return True
    if "fixtures" in parts:
        return True
    if rel.startswith("modules/commands-extra/skills/audit/"):
        return True
    if "/modules/commands-extra/skills/audit/" in ("/" + rel):
        return True
    return False


def allow_secret_line(line):
    """A matched secret/PII line is EXEMPT only under these narrow rules."""
    # Explicit opt-out marker for intentional illustrative content.
    if "ccgm-allow-secret" in line:
        return True
    if "__PLACEHOLDER__" in line:
        return True

    emails = EMAIL_RE.findall(line)
    if emails:
        real = [
            e
            for e in emails
            if not PLACEHOLDER_EMAIL_RE.search(e)
            and not TRIVIAL_EMAIL_RE.match(e)
        ]
        if not real:
            # Every email is a placeholder. Exempt only if no other (non-email)
            # token shape remains once the emails are stripped out.
            stripped = EMAIL_RE.sub("", line)
            if secret_re.search(stripped):
                return False  # leftover token shape present; do not exempt
            return True
        return False  # a real-looking email is present
    return False


def emit_offenders(rel, lines, pattern, exempt=None):
    out = []
    for idx, raw in enumerate(lines, start=1):
        line = raw.rstrip("\n").rstrip("\r")
        if pattern.search(line):
            if exempt is not None and exempt(line):
                continue
            out.append("%s:%d:%s" % (rel, idx, line))
    return out


def scan_identity(targets):
    offenders = []
    for target in targets:
        for path in walk_text_files(target):
            rel = relpath(path)
            # This script defines the identity/secret patterns literally.
            if rel == "tests/test-no-personal-data.sh":
                continue
            base = os.path.basename(rel)
            if base in ("README.md", "postInstall.sh"):
                pat = identity_relaxed_re
            else:
                pat = identity_re
            offenders.extend(emit_offenders(rel, read_lines(path), pat))
    return offenders


def scan_secret(root):
    offenders = []
    for path in walk_text_files(root):
        rel = relpath(path)
        if rel == "tests/test-no-personal-data.sh":
            continue
        if secret_path_excluded(rel):
            continue
        offenders.extend(
            emit_offenders(rel, read_lines(path), secret_re, exempt=allow_secret_line)
        )
    return offenders


def main(argv):
    if len(argv) < 2:
        sys.stderr.write("usage: scan <identity|secret> <path...>\n")
        return 2
    mode = argv[1]
    paths = argv[2:]
    if mode == "identity":
        offenders = scan_identity(paths)
    elif mode == "secret":
        if not paths:
            sys.stderr.write("secret scan requires a root path\n")
            return 2
        offenders = scan_secret(paths[0])
    else:
        sys.stderr.write("unknown mode: %s\n" % mode)
        return 2
    for line in offenders:
        sys.stdout.write(line + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
PY
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
  hits=$(REPO_ROOT="$tmp" run_scanner secret "$tmp/leak.txt")
  if [ -n "$hits" ]; then
    echo "  OK: detector flagged the planted token"
  else
    echo "  UNEXPECTED PASS: detector missed the planted token"
    rc=1
  fi

  echo "--- planted-PII-email file (expect DETECT) ---"
  hits=$(REPO_ROOT="$tmp" run_scanner secret "$tmp/pii.txt")
  if [ -n "$hits" ]; then
    echo "  OK: detector flagged the planted PII email"
  else
    echo "  UNEXPECTED PASS: detector missed the planted PII email"
    rc=1
  fi

  echo "--- clean file (expect PASS) ---"
  hits=$(REPO_ROOT="$tmp" run_scanner secret "$tmp/clean.txt")
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
export REPO_ROOT
identity_hits=$(run_scanner identity "${identity_targets[@]}")
secret_hits=$(run_scanner secret "$REPO_ROOT")

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
