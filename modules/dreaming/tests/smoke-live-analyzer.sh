#!/usr/bin/env bash
# Live-API smoke check for the Epic 3 analyzer (bizlogic-005).
#
# NOT part of the required offline test battery (test-dream-pipeline.sh /
# test_dream_analyze.py) -- this makes REAL Anthropic Messages API calls
# and costs real money. It exists to exercise the highest-uncertainty
# artifacts (the two prompts) against a real model once, per plan.md's
# Epic 3 acceptance checklist:
#
#   "Live-API smoke (bizlogic-005, gated on H1): one minimal real evidence
#    bundle through the real map->reduce path asserts >=1 schema-valid
#    proposal produced."
#
# Gated on H1 (an ANTHROPIC_API_KEY configured at ~/.claude/dreaming/.env
# or ~/.claude/autoheal/.env, §3.5's fallback order): SKIPS GRACEFULLY
# (exit 0, clear message) when neither file sets the key. Never fails the
# build over a missing key.
#
# Kept deliberately minimal/cheap: two small fixture transcripts (two
# copies of Epic 2's friction.jsonl, each already tiny, with the second
# copy's sessionId rewritten so the SAME friction cluster recurs across
# two distinct sessions -- see the "recurring pattern" note below for why
# a single copy is the wrong fixture for this test), a single slug, a
# single map call + a single reduce call.
#
# Usage: bash modules/dreaming/tests/smoke-live-analyzer.sh

set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MODULE_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
DREAM_ANALYZE="${MODULE_ROOT}/bin/dream-analyze.sh"
FRICTION_FIXTURE="${SCRIPT_DIR}/fixtures/friction.jsonl"

DREAMING_ENV="${HOME}/.claude/dreaming/.env"
AUTOHEAL_ENV="${HOME}/.claude/autoheal/.env"

if ! grep -q '^ANTHROPIC_API_KEY=' "${DREAMING_ENV}" 2>/dev/null \
   && ! grep -q '^ANTHROPIC_API_KEY=' "${AUTOHEAL_ENV}" 2>/dev/null; then
    echo "smoke-live-analyzer: no ANTHROPIC_API_KEY at ${DREAMING_ENV} or ${AUTOHEAL_ENV}; skipping (H1 not configured)." >&2
    exit 0
fi

SANDBOX="$(mktemp -d -t dream_live_smoke.XXXXXX)"
trap 'rm -rf "${SANDBOX}"' EXIT

DREAMING_DIR="${SANDBOX}/dreaming"
LEARNINGS_DIR="${SANDBOX}/learnings"
PROJECTS_ROOT="${SANDBOX}/claude-projects"
mkdir -p "${DREAMING_DIR}" "${LEARNINGS_DIR}" "${PROJECTS_ROOT}/session-a" "${PROJECTS_ROOT}/session-b"
cp "${FRICTION_FIXTURE}" "${PROJECTS_ROOT}/session-a/friction.jsonl"
# Root-caused during initial smoke runs: a SINGLE one-off session is a
# genuinely weak, borderline signal (dreaming-prompt-map.md's own guidance:
# "a single occurrence" is much weaker than "recurs across multiple
# distinct sample_session_ids"), and a well-calibrated real model
# legitimately (and correctly) sometimes declines to propose from it --
# observed both outcomes across repeated live runs of the single-session
# fixture. Duplicating it under a second sessionId gives the SAME friction
# cluster two distinct sample_session_ids, an unambiguous recurring
# pattern, without changing what is being tested (the real map->reduce
# prompts against real friction data).
sed 's/fixture-friction-0001/fixture-friction-0002/g' "${FRICTION_FIXTURE}" > "${PROJECTS_ROOT}/session-b/friction.jsonl"

# Leave max_output_tokens at its production default (16000). A lower cap
# was tried here and reliably truncated real responses: an earlier run at
# 1024 cut the JSON off mid-response while the production default did
# not. Since #1026 the map and reduce calls both disable thinking, so
# thinking tokens no longer share the budget -- but the cap stays a
# backstop either way, and cost stays bounded by daily_cost_cap_usd
# rather than by an unrealistically tight output cap.
cat > "${DREAMING_DIR}/config.json" <<'JSON'
{"daily_cost_cap_usd": 1.0}
JSON

echo "smoke-live-analyzer: key found, running ONE real map + ONE real reduce call..." >&2

env \
    HOME="${SANDBOX}/home" \
    CCGM_DREAMING_DIR="${DREAMING_DIR}" \
    CCGM_LEARNINGS_DIR="${LEARNINGS_DIR}" \
    CCGM_DREAMING_ENV_FILE="${DREAMING_ENV}" \
    CCGM_DREAMING_AUTOHEAL_ENV_FILE="${AUTOHEAL_ENV}" \
    bash "${DREAM_ANALYZE}" \
        --force-day 2026-01-01 \
        --slugs widget-app \
        --projects-root "${PROJECTS_ROOT}" \
    >"${SANDBOX}/analyze.out" 2>"${SANDBOX}/analyze.err"
RC=$?

echo "--- dream-analyze.sh stdout ---"
cat "${SANDBOX}/analyze.out"
echo "--- dream-analyze.sh stderr ---"
cat "${SANDBOX}/analyze.err"

if [ "${RC}" -ne 0 ]; then
    echo "smoke-live-analyzer: dream-analyze.sh exited ${RC}" >&2
    exit 1
fi

PROPOSALS_FILE="${DREAMING_DIR}/proposals/2026-01-01.jsonl"
if [ ! -f "${PROPOSALS_FILE}" ]; then
    echo "smoke-live-analyzer: FAIL — no proposals file written (proposals_written may be 0; a real model can legitimately decide there is nothing to propose, but this fixture is designed to be obviously proposal-worthy)." >&2
    exit 1
fi


# grep -c prints "0" (exit 1) for an existing-but-empty file and prints
# NOTHING (exit 2) for a missing file -- `|| echo 0` on top of that would
# double-print "0\n0" for the empty-file case. Capture stdout only and
# default on emptiness, not on exit code.
COUNT="$(grep -c . "${PROPOSALS_FILE}" 2>/dev/null)"
COUNT="${COUNT:-0}"
echo "smoke-live-analyzer: ${COUNT} proposal(s) written." >&2

if [ "${COUNT}" -lt 1 ]; then
    echo "smoke-live-analyzer: FAIL — expected >=1 schema-valid proposal, got 0." >&2
    exit 1
fi

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

if [ -n "${SCHEMA_ERRORS}" ]; then
    echo "smoke-live-analyzer: FAIL — schema validation errors:" >&2
    echo "${SCHEMA_ERRORS}" >&2
    exit 1
fi

echo "smoke-live-analyzer: PASS — ${COUNT} schema-valid proposal(s) from a real map->reduce call." >&2
exit 0
