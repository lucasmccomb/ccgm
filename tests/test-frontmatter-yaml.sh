#!/usr/bin/env bash
set -euo pipefail

# CCGM Command/Skill/Agent Frontmatter YAML Guard (issue #709)
#
# Claude Code parses command/skill/agent frontmatter with a STRICT YAML parser.
# A value like `argument-hint: [a] [b]` is read as a flow sequence and fails to
# parse, at which point ALL frontmatter fields are silently dropped at load time.
#
# This guard scans every:
#   modules/**/commands/*.md
#   modules/**/skills/**/SKILL.md
#   modules/**/agents/*.md
#
# extracts the leading `---`...`---` frontmatter, and FAILS if:
#   - the frontmatter block is malformed (opens with `---` but never closes), or
#   - any top-level value is an UNQUOTED flow collection (starts with `[` or `{`).
#
# It does NOT implement full YAML. It deterministically detects the specific
# breakage class above, which is the one that bites Claude Code command loading.
#
# Dependency-free: python3 stdlib only (no pyyaml). Portable: macOS BSD + Linux.

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

if ! command -v python3 >/dev/null 2>&1; then
  echo "FAIL: python3 is required for tests/test-frontmatter-yaml.sh" >&2
  exit 1
fi

# Write the dependency-free checker to a temp file so single/double quotes in the
# Python source never collide with the surrounding shell quoting.
WORKDIR="$(mktemp -d "${TMPDIR:-/tmp}/ccgm-fm.XXXXXX")"
cleanup() { rm -rf "$WORKDIR"; }
trap cleanup EXIT

CHECKER="$WORKDIR/check_frontmatter.py"
cat >"$CHECKER" <<'PYEOF'
import sys, re

# The breakage class: a top-level value that begins with an unquoted flow
# collection indicator. Quoted scalars are always safe.
FLOW_OPENERS = ("[", "{")


def frontmatter(text):
    # Must start at byte 0 with a --- line.
    if not text.startswith("---"):
        return None, None  # no frontmatter -> nothing to check
    m = re.match(r"^---[ \t]*\r?\n(.*?)\r?\n---[ \t]*(\r?\n|$)", text, re.S)
    if not m:
        return None, "frontmatter opens with --- but is never closed by a --- line"
    return m.group(1), None


def value_is_unquoted_flow(val):
    v = val.strip()
    if not v:
        return False
    c = v[0]
    if c == '"' or c == "'":
        return False  # quoted scalar, safe
    return c in FLOW_OPENERS


def main():
    violations = 0
    for raw in sys.stdin.read().splitlines():
        path = raw.strip()
        if not path:
            continue
        try:
            with open(path, encoding="utf-8") as fh:
                text = fh.read()
        except OSError as exc:
            print("%s: cannot read (%s)" % (path, exc))
            violations += 1
            continue

        fm, err = frontmatter(text)
        if err:
            print("%s: %s" % (path, err))
            violations += 1
            continue
        if fm is None:
            # No frontmatter block; not the breakage class this guard targets.
            continue

        for line in fm.split("\n"):
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            if line[:1] == " " or line[:1] == "\t":
                continue  # nested mapping/sequence content; not a top-level scalar
            if line.lstrip().startswith("-"):
                continue
            if ":" not in line:
                print("%s: malformed frontmatter line (no key): %r" % (path, line))
                violations += 1
                continue
            key, _, val = line.partition(":")
            if value_is_unquoted_flow(val):
                print("%s: key %r has an unquoted flow value (quote it): %r"
                      % (path, key.strip(), val.strip()))
                violations += 1

    if violations:
        print("\n%d frontmatter violation(s) found." % violations)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
PYEOF

collect_targets() {
  # Print every target md path, one per line. CCGM paths contain no newlines.
  find modules -type f \
    \( -path 'modules/*/commands/*.md' \
       -o -path 'modules/*/skills/*/SKILL.md' \
       -o -path 'modules/*/skills/SKILL.md' \
       -o -path 'modules/*/agents/*.md' \) \
    | sort
}

# --- Self-check: a planted bad fixture must FAIL, a clean one must PASS --------
BAD_FIXTURE="$WORKDIR/bad.md"
GOOD_FIXTURE="$WORKDIR/good.md"

cat >"$BAD_FIXTURE" <<'EOF'
---
description: planted bad fixture
argument-hint: [--flag] [arg]
---
body
EOF

cat >"$GOOD_FIXTURE" <<'EOF'
---
description: planted good fixture
argument-hint: "[--flag] [arg]"
---
body
EOF

echo "self-test: bad fixture must FAIL..."
if printf '%s\n' "$BAD_FIXTURE" | python3 "$CHECKER" >/dev/null 2>&1; then
  echo "FAIL: planted bad fixture was accepted; the guard is not catching the breakage class" >&2
  exit 1
fi
echo "ok: bad fixture rejected"

echo "self-test: good fixture must PASS..."
if ! printf '%s\n' "$GOOD_FIXTURE" | python3 "$CHECKER" >/dev/null 2>&1; then
  echo "FAIL: planted good fixture was rejected; the guard has a false positive" >&2
  exit 1
fi
echo "ok: good fixture accepted"

# --- Real scan --------------------------------------------------------------
COUNT=$(collect_targets | grep -c . || true)
echo "Scanning $COUNT command/skill/agent frontmatter file(s)..."

if collect_targets | python3 "$CHECKER"; then
  echo "test-frontmatter-yaml.sh: all frontmatter valid"
else
  echo "" >&2
  echo "test-frontmatter-yaml.sh: frontmatter validation failed." >&2
  echo "Quote any value that starts with [ or { as a double-quoted string." >&2
  exit 1
fi
