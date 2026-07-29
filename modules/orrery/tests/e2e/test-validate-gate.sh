#!/usr/bin/env bash
set -euo pipefail

# Validate-gate E2E (plan Epic 1 / section 3.7, arch C1).
#
# Against the checked-in broken model:
#   - likec4 validate --json exits 1 with parseable, structured error JSON
#     (valid=false, errors[] with message entries) - validate IS the gate
#   - likec4 build exits 0 on the same garbage - documented here so nobody
#     ever mistakes the build exit code for a gate

MODULE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SCRIPTS="$MODULE_DIR/skills/orrery/scripts"
BROKEN="$MODULE_DIR/tests/fixtures/broken-model"

WORK="$(mktemp -d "${TMPDIR:-/tmp}/orrery-validate.XXXXXX")"
trap 'rm -rf "$WORK"' EXIT

fail() {
  echo "FAIL: $1" >&2
  exit 1
}

# --- validate must exit 1 with structured JSON -------------------------------
# Stderr deliberately NOT suppressed: on a cold cache this call runs npm ci,
# and its failure must stay loud instead of dying with zero explanation.
set +e
VALIDATE_OUT="$(bash "$SCRIPTS/likec4.sh" validate --json "$BROKEN")"
VALIDATE_CODE=$?
set -e

[ "$VALIDATE_CODE" = "1" ] || fail "validate exited $VALIDATE_CODE on the broken model (expected 1)"
echo "ok: validate exits 1 on the broken model"

printf '%s' "$VALIDATE_OUT" | python3 -c '
import json, sys
d = json.load(sys.stdin)
assert d.get("valid") is False, "expected valid=false"
errs = d.get("errors")
assert isinstance(errs, list) and len(errs) >= 1, "expected a non-empty errors[] list"
for e in errs:
    assert "message" in e, "each error must carry a message"
print("ok: validate output is parseable structured JSON (%d error(s))" % len(errs))
' || fail "validate output is not the expected structured JSON"

# --- build must exit 0 on the same garbage (never a gate) --------------------
set +e
bash "$SCRIPTS/likec4.sh" build --output-single-file --base ./ -o "$WORK/dist" "$BROKEN" >/dev/null 2>&1
BUILD_CODE=$?
set -e

[ "$BUILD_CODE" = "0" ] || fail "build exited $BUILD_CODE on the broken model (expected 0 - the documented always-0 behavior changed; re-verify the gate design)"
echo "ok: build exits 0 on the broken model (documented; never used as a gate)"

echo "test-validate-gate.sh: PASS"
