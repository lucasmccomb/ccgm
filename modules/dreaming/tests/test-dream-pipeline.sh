#!/usr/bin/env bash
# Offline end-to-end test for the Epic 3 dreaming pipeline:
#   real transcript fixture (Epic 2's friction.jsonl) -> real miner
#   (discover + mine_to_evidence_bundle, no mocking) -> --offline analyzer
#   (canned map/reduce responses under tests/fixtures/offline-responses/,
#   NO network, NO ANTHROPIC_API_KEY) -> proposals/{date}.jsonl -> digest.
#
# Coverage (plan.md §5 Epic 3 "Tests"):
#   - offline mode never invokes curl at all (PATH shim asserts this)
#   - every written proposal row validates against proposal-schema.json
#   - the under-prevalent `_global` proposal in the canned reduce response
#     is DOWNGRADED (needs_manual_promotion marker), never dropped
#     (adrev-009 / adrev-405)
#   - an injection-shaped string in the canned reduce response is
#     neutralized in the written file (sec-3)
#   - the watermark advances for the mined slug
#   - dream-digest.sh renders a digest that surfaces the same signals
#
# Isolated: never touches the real ~/.claude/{dreaming,learnings} or
# ~/.claude/projects/. All state lives under a mktemp sandbox, cleaned up
# on exit.

set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MODULE_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
DREAM_ANALYZE="${MODULE_ROOT}/bin/dream-analyze.sh"
DREAM_DIGEST="${MODULE_ROOT}/bin/dream-digest.sh"
OFFLINE_FIXTURES="${SCRIPT_DIR}/fixtures/offline-responses"
FRICTION_FIXTURE="${SCRIPT_DIR}/fixtures/friction.jsonl"

PASS=0
FAIL=0

assert_eq() {
    local actual="$1" expected="$2" label="$3"
    if [ "${actual}" = "${expected}" ]; then
        PASS=$((PASS + 1))
    else
        FAIL=$((FAIL + 1))
        echo "FAIL: ${label}"
        echo "  expected: ${expected}"
        echo "  actual:   ${actual}"
    fi
}

assert_contains() {
    local haystack="$1" needle="$2" label="$3"
    case "${haystack}" in
        *"${needle}"*) PASS=$((PASS + 1)) ;;
        *)
            FAIL=$((FAIL + 1))
            echo "FAIL: ${label}"
            echo "  expected substring: ${needle}"
            echo "  actual (first 500): ${haystack:0:500}"
            ;;
    esac
}

assert_not_contains() {
    local haystack="$1" needle="$2" label="$3"
    case "${haystack}" in
        *"${needle}"*)
            FAIL=$((FAIL + 1))
            echo "FAIL: ${label}"
            echo "  did not expect substring: ${needle}"
            ;;
        *) PASS=$((PASS + 1)) ;;
    esac
}

assert_file_exists() {
    local path="$1" label="$2"
    if [ -f "${path}" ]; then
        PASS=$((PASS + 1))
    else
        FAIL=$((FAIL + 1))
        echo "FAIL: ${label}"
        echo "  expected file: ${path}"
    fi
}

assert_file_not_exists() {
    local path="$1" label="$2"
    if [ ! -e "${path}" ]; then
        PASS=$((PASS + 1))
    else
        FAIL=$((FAIL + 1))
        echo "FAIL: ${label}"
        echo "  did not expect file to exist: ${path}"
    fi
}

# ---------------------------------------------------------------------
# Sandbox setup.
# ---------------------------------------------------------------------

SANDBOX="$(mktemp -d -t dream_pipeline.XXXXXX)"
trap 'rm -rf "${SANDBOX}"' EXIT

DREAMING_DIR="${SANDBOX}/dreaming"
LEARNINGS_DIR="${SANDBOX}/learnings"
PROJECTS_ROOT="${SANDBOX}/claude-projects"
mkdir -p "${DREAMING_DIR}" "${LEARNINGS_DIR}" "${PROJECTS_ROOT}/session-a"

# discover() requires transcripts to live inside a subdirectory of
# projects_root (mirrors the real ~/.claude/projects/<cwd-slug>/*.jsonl
# layout) -- the subdirectory NAME is irrelevant, slug identity is
# re-derived from the transcript's own `cwd` field (arch-1). cp (not a
# symlink with a preserved old mtime) so discover()'s lookback-days cutoff
# sees a fresh mtime regardless of the fixture content's own 2026-01-01
# timestamps.
cp "${FRICTION_FIXTURE}" "${PROJECTS_ROOT}/session-a/friction.jsonl"

# Fake curl: writes a sentinel and fails loudly if ever invoked. --offline
# mode must never touch curl at all.
FAKEBIN="${SANDBOX}/fakebin"
mkdir -p "${FAKEBIN}"
CURL_SENTINEL="${SANDBOX}/curl-was-invoked"
cat > "${FAKEBIN}/curl" <<EOF
#!/usr/bin/env bash
echo "FAKE CURL INVOKED -- offline mode must never call curl" >&2
touch "${CURL_SENTINEL}"
exit 1
EOF
chmod +x "${FAKEBIN}/curl"

RUN_ENV=(
    HOME="${SANDBOX}/home"
    PATH="${FAKEBIN}:${PATH}"
    CCGM_DREAMING_DIR="${DREAMING_DIR}"
    CCGM_LEARNINGS_DIR="${LEARNINGS_DIR}"
)

# ---------------------------------------------------------------------
# Step 1: dream-analyze.sh --offline, real miner, real fixture.
# ---------------------------------------------------------------------

env "${RUN_ENV[@]}" bash "${DREAM_ANALYZE}" \
    --offline "${OFFLINE_FIXTURES}" \
    --force-day 2026-01-01 \
    --slugs widget-app \
    --projects-root "${PROJECTS_ROOT}" \
    >"${SANDBOX}/analyze.out" 2>"${SANDBOX}/analyze.err"
ANALYZE_RC=$?

assert_eq "${ANALYZE_RC}" "0" "dream-analyze.sh --offline exits 0"
assert_file_not_exists "${CURL_SENTINEL}" "offline mode never invokes curl"

PROPOSALS_FILE="${DREAMING_DIR}/proposals/2026-01-01.jsonl"
assert_file_exists "${PROPOSALS_FILE}" "proposals file written"

if [ -f "${PROPOSALS_FILE}" ]; then
    # grep -c prints "0" (exit 1) for an existing-but-empty file and NOTHING
    # (exit 2) for a missing file -- `|| echo 0` on top of that would
    # double-print "0\n0" for the empty-file case. Capture stdout only and
    # default on emptiness, not on exit code.
    LINE_COUNT="$(grep -c . "${PROPOSALS_FILE}" 2>/dev/null)"
    LINE_COUNT="${LINE_COUNT:-0}"
    assert_eq "${LINE_COUNT}" "3" "all 3 canned proposals were written (none spuriously rejected)"

    RAW="$(cat "${PROPOSALS_FILE}")"

    # --- Schema validation: every row validates against proposal-schema.json,
    # using the SAME shared stdlib validator dream_analyze.py itself uses.
    SCHEMA_ERRORS="$(
        PROPOSALS_FILE="${PROPOSALS_FILE}" MODULE_ROOT="${MODULE_ROOT}" python3 - <<'PY'
import json
import os
import sys

sys.path.insert(0, os.path.join(os.environ["MODULE_ROOT"], "lib"))
import transcript_miner as tm

schema = json.load(open(os.path.join(os.environ["MODULE_ROOT"], "lib", "proposal-schema.json")))
errors = []
with open(os.environ["PROPOSALS_FILE"], "r", encoding="utf-8") as fh:
    for i, line in enumerate(fh):
        line = line.strip()
        if not line:
            continue
        row = json.loads(line)
        errs = tm.validate_against_schema(row, schema)
        if errs:
            errors.append(f"line {i}: {errs}")
print("\n".join(errors))
PY
    )"
    assert_eq "${SCHEMA_ERRORS}" "" "every written proposal validates against proposal-schema.json"

    # --- Breadth downgrade (adrev-009/adrev-405): the under-prevalent
    # `_global` proposal is present with a needs_manual_promotion marker
    # pointing at /dream-apply, not the ADMIN hatch.
    assert_contains "${RAW}" '"project": "_global"' "under-prevalent _global proposal was NOT dropped"
    assert_contains "${RAW}" "needs_manual_promotion" "_global proposal carries the needs_manual_promotion marker"
    assert_contains "${RAW}" "sessions=1, agents=1" "marker reports the observed (under-threshold) prevalence"
    assert_contains "${RAW}" "/dream-apply" "marker points at /dream-apply, not the ADMIN hatch"
    assert_not_contains "${RAW}" "CCGM_LEARNINGS_ADMIN" "marker never names the terminal-only ADMIN hatch"

    # --- Sanitization (sec-3): the injection-shaped canned proposal is
    # neutralized, not passed through verbatim.
    assert_contains "${RAW}" "[neutralized]" "injection-shaped content/justification is neutralized before writing"

    # --- Every row starts pending.
    STATUS_COUNT="$(printf '%s\n' "${RAW}" | grep -o '"status": "pending"' | wc -l | tr -d ' ')"
    assert_eq "${STATUS_COUNT}" "3" "every proposal starts status=pending"
fi

# --- Watermark advanced for the mined slug.
WATERMARK_FILE="${DREAMING_DIR}/state/last-dreamed.json"
assert_file_exists "${WATERMARK_FILE}" "watermark file written"
if [ -f "${WATERMARK_FILE}" ]; then
    WM_BODY="$(cat "${WATERMARK_FILE}")"
    assert_contains "${WM_BODY}" "widget-app" "watermark advanced for the mined slug"
fi

# --- Run summary written for the digest to read.
RUN_SUMMARY="${DREAMING_DIR}/state/runs/2026-01-01.json"
assert_file_exists "${RUN_SUMMARY}" "run summary written"
if [ -f "${RUN_SUMMARY}" ]; then
    RS_WRITTEN="$(python3 -c "import json; print(json.load(open('${RUN_SUMMARY}'))['proposals_written'])")"
    assert_eq "${RS_WRITTEN}" "3" "run summary reports 3 proposals written"
fi

# ---------------------------------------------------------------------
# Step 2: dream-digest.sh renders the same signals.
# ---------------------------------------------------------------------

env "${RUN_ENV[@]}" bash "${DREAM_DIGEST}" 2026-01-01 \
    >"${SANDBOX}/digest.out" 2>"${SANDBOX}/digest.err"
DIGEST_RC=$?
assert_eq "${DIGEST_RC}" "0" "dream-digest.sh exits 0"

DIGEST_FILE="${DREAMING_DIR}/digests/2026-01-01.md"
assert_file_exists "${DIGEST_FILE}" "digest file written"
if [ -f "${DIGEST_FILE}" ]; then
    DIGEST_BODY="$(cat "${DIGEST_FILE}")"
    assert_contains "${DIGEST_BODY}" "widget-app" "digest shows the widget-app project section"
    assert_contains "${DIGEST_BODY}" "_global" "digest shows the _global project section"
    assert_contains "${DIGEST_BODY}" "needs_manual_promotion" "digest surfaces the breadth-gate marker"
    assert_contains "${DIGEST_BODY}" "3 proposal" "digest reports the proposal count"
fi

# ---------------------------------------------------------------------
# Summary.
# ---------------------------------------------------------------------

echo ""
echo "=== test-dream-pipeline.sh: ${PASS} passed, ${FAIL} failed ==="
if [ "${FAIL}" -gt 0 ]; then
    echo "--- analyze.out ---"; cat "${SANDBOX}/analyze.out"
    echo "--- analyze.err ---"; cat "${SANDBOX}/analyze.err"
    echo "--- digest.err ---"; cat "${SANDBOX}/digest.err"
    exit 1
fi
exit 0
