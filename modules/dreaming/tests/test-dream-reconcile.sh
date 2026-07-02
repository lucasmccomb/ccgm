#!/usr/bin/env bash
# Idempotency test for dream-reconcile.sh (#775 Stage-2 Recommend).
#
# Coverage:
#   - a same-day re-run does NOT duplicate the "## Reconciliation" section
#     (dreaming.md's own "Quick checks" recommends re-running
#     `dream-daily.sh --force-day <date>` for local smoke testing, which is
#     exactly the scenario that trips this)
#   - content OTHER sections (e.g. dream-digest.sh's own "## Run summary" /
#     "## Proposals") already present in the digest file survive a
#     dream-reconcile.sh re-run untouched -- this step is scoped to just
#     its own section, never the rest of the file
#   - the re-run's freshly computed section reflects current state (not a
#     stale copy of the first run)
#
# Isolated: never touches the real ~/.claude/{dreaming,learnings} or
# ~/.claude/projects/. All state lives under a mktemp sandbox, cleaned up
# on exit.

set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MODULE_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
DREAM_RECONCILE="${MODULE_ROOT}/bin/dream-reconcile.sh"

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

# ---------------------------------------------------------------------
# Sandbox setup.
# ---------------------------------------------------------------------

SANDBOX="$(mktemp -d -t dream_reconcile.XXXXXX)"
trap 'rm -rf "${SANDBOX}"' EXIT

DREAMING_DIR="${SANDBOX}/dreaming"
PROJECTS_ROOT="${SANDBOX}/claude-projects"
mkdir -p "${DREAMING_DIR}/digests"

# A real harness project dir + transcript + fact file, so the reconciliation
# section has real per-slug content to compare across runs (not just the
# "no auto-memory directories found" boilerplate).
HARNESS_DIR="${PROJECTS_ROOT}/-Users-fixtureuser-code-idem-repo"
mkdir -p "${HARNESS_DIR}/memory"
printf '{"cwd": "/Users/fixtureuser/code/idem-repo", "type": "user"}\n' >"${HARNESS_DIR}/session-1.jsonl"
cat >"${HARNESS_DIR}/memory/fact.md" <<'EOF'
---
name: idem-fact
description: a fact used to verify dream-reconcile.sh is idempotent
metadata:
  node_type: memory
  type: project
  originSessionId: aaaa-bbbb-cccc-dddd
---

Body.
EOF

RUN_ENV=(
    HOME="${SANDBOX}/home"
    CCGM_DREAMING_DIR="${DREAMING_DIR}"
    CCGM_DREAMING_PROJECTS_ROOT="${PROJECTS_ROOT}"
)

DATE="2026-05-01"
DIGEST_FILE="${DREAMING_DIR}/digests/${DATE}.md"

# Pre-seed the digest with content shaped like dream-digest.sh's own output
# (chain step 2, which always runs immediately before dream-reconcile.sh)
# so the test also proves this step never touches sections it does not own.
cat >"${DIGEST_FILE}" <<EOF
# Dreaming digest -- ${DATE}

## Run summary

- offline: true
- slugs considered: 1

## Proposals

_No proposals for this date._

---

**Controls**

- \`/dream\` — status
EOF

# ---------------------------------------------------------------------
# Run 1: first reconciliation append.
# ---------------------------------------------------------------------

env "${RUN_ENV[@]}" bash "${DREAM_RECONCILE}" "${DATE}" \
    >"${SANDBOX}/run1.out" 2>"${SANDBOX}/run1.err"
RUN1_RC=$?
assert_eq "${RUN1_RC}" "0" "dream-reconcile.sh (run 1) exits 0"
assert_file_exists "${DIGEST_FILE}" "digest file exists after run 1"

if [ -f "${DIGEST_FILE}" ]; then
    BODY1="$(cat "${DIGEST_FILE}")"
    RECON_COUNT_1="$(grep -c '^## Reconciliation$' "${DIGEST_FILE}")"
    assert_eq "${RECON_COUNT_1}" "1" "exactly one Reconciliation section after run 1"
    assert_contains "${BODY1}" "### idem-repo" "run 1 digest shows the idem-repo section"
    assert_contains "${BODY1}" "idem-fact" "run 1 digest shows the fact"
    assert_contains "${BODY1}" "## Run summary" "run 1 preserves the pre-existing Run summary section"
fi

# ---------------------------------------------------------------------
# Run 2: same-day re-run (the scenario dreaming.md's "Quick checks"
# documents via `dream-daily.sh --force-day <date>`). Must NOT duplicate
# the Reconciliation section.
# ---------------------------------------------------------------------

env "${RUN_ENV[@]}" bash "${DREAM_RECONCILE}" "${DATE}" \
    >"${SANDBOX}/run2.out" 2>"${SANDBOX}/run2.err"
RUN2_RC=$?
assert_eq "${RUN2_RC}" "0" "dream-reconcile.sh (run 2, same-day re-run) exits 0"

# ---------------------------------------------------------------------
# Run 3: a third consecutive re-run, to prove this isn't a "fixed after
# exactly two" artifact.
# ---------------------------------------------------------------------

env "${RUN_ENV[@]}" bash "${DREAM_RECONCILE}" "${DATE}" \
    >"${SANDBOX}/run3.out" 2>"${SANDBOX}/run3.err"
RUN3_RC=$?
assert_eq "${RUN3_RC}" "0" "dream-reconcile.sh (run 3) exits 0"

if [ -f "${DIGEST_FILE}" ]; then
    BODY3="$(cat "${DIGEST_FILE}")"
    RECON_COUNT_3="$(grep -c '^## Reconciliation$' "${DIGEST_FILE}")"
    assert_eq "${RECON_COUNT_3}" "1" "exactly one Reconciliation section after 3 runs (no duplication)"

    RUN_SUMMARY_COUNT="$(grep -c '^## Run summary$' "${DIGEST_FILE}")"
    assert_eq "${RUN_SUMMARY_COUNT}" "1" "pre-existing Run summary section still appears exactly once (untouched by 3 reconcile re-runs)"

    PROPOSALS_COUNT="$(grep -c '^## Proposals$' "${DIGEST_FILE}")"
    assert_eq "${PROPOSALS_COUNT}" "1" "pre-existing Proposals section still appears exactly once"

    IDEM_REPO_COUNT="$(grep -c '^### idem-repo$' "${DIGEST_FILE}")"
    assert_eq "${IDEM_REPO_COUNT}" "1" "idem-repo subsection appears exactly once (not duplicated across runs)"

    assert_contains "${BODY3}" "idem-fact" "content still present after 3 re-runs"
    assert_contains "${BODY3}" "\`/dream\` — status" "Controls section (which contains an unrelated '/dream' line, not a heading) survives untouched"
fi

# ---------------------------------------------------------------------
# Run 4: content changes between runs (a second fact appears) -- the
# re-run must reflect the FRESH state, not a stale first-run snapshot.
# ---------------------------------------------------------------------

cat >"${HARNESS_DIR}/memory/fact2.md" <<'EOF'
---
name: idem-fact-two
description: a second fact added before the fourth reconcile run
metadata:
  node_type: memory
  type: project
  originSessionId: eeee-ffff-0000-1111
---

Body.
EOF

env "${RUN_ENV[@]}" bash "${DREAM_RECONCILE}" "${DATE}" \
    >"${SANDBOX}/run4.out" 2>"${SANDBOX}/run4.err"
RUN4_RC=$?
assert_eq "${RUN4_RC}" "0" "dream-reconcile.sh (run 4, after a new fact appeared) exits 0"

if [ -f "${DIGEST_FILE}" ]; then
    BODY4="$(cat "${DIGEST_FILE}")"
    RECON_COUNT_4="$(grep -c '^## Reconciliation$' "${DIGEST_FILE}")"
    assert_eq "${RECON_COUNT_4}" "1" "still exactly one Reconciliation section after run 4"
    assert_contains "${BODY4}" "idem-fact-two" "run 4 reflects the newly added fact (fresh recompute, not a stale cached section)"
    assert_contains "${BODY4}" "2 auto-memory fact(s)" "fact count updates to 2 on the fresh run"
fi

# ---------------------------------------------------------------------
# Summary.
# ---------------------------------------------------------------------

echo ""
echo "=== test-dream-reconcile.sh: ${PASS} passed, ${FAIL} failed ==="
if [ "${FAIL}" -gt 0 ]; then
    echo "--- run1.err ---"; cat "${SANDBOX}/run1.err"
    echo "--- run2.err ---"; cat "${SANDBOX}/run2.err"
    echo "--- run3.err ---"; cat "${SANDBOX}/run3.err"
    echo "--- run4.err ---"; cat "${SANDBOX}/run4.err"
    echo "--- final digest ---"; cat "${DIGEST_FILE}" 2>/dev/null
    exit 1
fi
exit 0
