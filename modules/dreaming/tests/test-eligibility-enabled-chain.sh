#!/usr/bin/env bash
# Enabled-mode chain smoke for the composite-eligibility gate
# (composite-eligibility plan.md §8.3 / Epic E4 fixture-triple + positive
# assertion; Epic E6 wires this into CI).
#
# This is the ONLY continuous end-to-end exercise of the feature's own path:
#   mine -> analyze -> stamp_proposal_signals() -> composite gate -> apply -> digest,
# under BOTH optimistic_integration.enabled AND .eligibility.enabled = true.
#
# It satisfies all four §8.3 preconditions and then POSITIVELY asserts a real
# ELIGIBLE (decision_basis="composite") outcome reached the apply-audit. A run
# that exits 0 without the composite having run is a RED check here -- the whole
# point is that a silently-skipped optimistic-integrate (outer flag off, eval
# gate closed, or every row skipped_origin) FAILS this smoke.
#
# Preconditions wired (plan.md §8.3):
#   1. Both flags true, via the committed minimal fixture eligibility-enabled-config.json.
#   2. CCGM_DREAMING_EVAL_SCRIPT -> a green stub (the live #788 gate would fail closed).
#   3. A synthetic transcript under CCGM_CLAUDE_PROJECTS_DIR that the offline
#      reduce fixture's learning_add resolves to (slug + excerpt) -> ELIGIBLE.
#   4. Positive assertion: an eligible/composite record with a per-signal breakdown.
#
# No network, no ANTHROPIC_API_KEY (offline), never the real store/dreaming/HOME.
#
# Usage: bash modules/dreaming/tests/test-eligibility-enabled-chain.sh
# Exit: 0 = PASS (composite proven), non-zero = FAIL.

set -u

TESTS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MODULE_ROOT="$(cd "${TESTS_DIR}/.." && pwd)"
FIXTURES="${TESTS_DIR}/fixtures"
OFFLINE_DIR="${FIXTURES}/offline-responses-eligible"
CONFIG_FIXTURE="${FIXTURES}/eligibility-enabled-config.json"
EVAL_STUB="${OFFLINE_DIR}/dream-eval-green-stub.sh"

DAY="2026-07-05"

fail() { echo "FAIL: $*" >&2; exit 1; }

for f in "${CONFIG_FIXTURE}" "${OFFLINE_DIR}/reduce.json" "${EVAL_STUB}" \
         "${TESTS_DIR}/seed_eligible_transcripts.py"; do
    [ -f "${f}" ] || fail "missing fixture: ${f}"
done

WORK="$(mktemp -d)"
trap 'rm -rf "${WORK}"' EXIT
export CCGM_DREAMING_DIR="${WORK}/dreaming"
export CCGM_LEARNINGS_DIR="${WORK}/learnings"
export CCGM_CLAUDE_PROJECTS_DIR="${WORK}/projects"
export HOME="${WORK}/home"            # never touch the real ~/.claude
export CCGM_DREAMING_EVAL_SCRIPT="${EVAL_STUB}"   # precondition 2: green gate
mkdir -p "${CCGM_DREAMING_DIR}" "${CCGM_LEARNINGS_DIR}" "${CCGM_CLAUDE_PROJECTS_DIR}" "${HOME}"

# Precondition 1: both flags true, via the committed minimal fixture.
cp "${CONFIG_FIXTURE}" "${CCGM_DREAMING_DIR}/config.json"

# Precondition 3: seed the synthetic transcript the reduce fixture resolves to.
python3 "${TESTS_DIR}/seed_eligible_transcripts.py" "${CCGM_CLAUDE_PROJECTS_DIR}" >/dev/null \
    || fail "could not seed the synthetic transcript"

# Run the enabled-mode chain (analyze -> optimistic-integrate -> digest), offline.
CHAIN_OUT="$(bash "${MODULE_ROOT}/bin/dream-daily.sh" \
    --offline "${OFFLINE_DIR}" \
    --force-day "${DAY}" \
    --slugs eligible-demo \
    --projects-root "${CCGM_CLAUDE_PROJECTS_DIR}" 2>&1)"
CHAIN_RC=$?
echo "${CHAIN_OUT}"
[ "${CHAIN_RC}" -eq 0 ] || fail "dream-daily.sh exited ${CHAIN_RC}"

# Guard against a vacuous green: the optimistic-integrate step must NOT have been
# skipped (outer flag off) or failed closed (eval gate). Its skip lines are
# distinctive; their presence is an immediate RED.
if echo "${CHAIN_OUT}" | grep -q "optimistic-integrate: optimistic_integration.enabled=false"; then
    fail "optimistic-integrate was SKIPPED (outer flag off) -- the composite never ran"
fi
if echo "${CHAIN_OUT}" | grep -q "failing closed"; then
    fail "optimistic-integrate failed closed (eval gate) -- the composite never ran"
fi

# Positive assertion (precondition 4): the apply-audit carries an ELIGIBLE
# (decision_basis="composite") record with a full per-signal breakdown, and the
# cited proposal actually applied. Deterministic parsing in python, not grep.
AUDIT="${CCGM_DREAMING_DIR}/state/apply-audit.jsonl"
PROPOSALS="${CCGM_DREAMING_DIR}/proposals/${DAY}.jsonl"
python3 - "${AUDIT}" "${PROPOSALS}" <<'PY' || fail "positive assertion failed"
import json, sys
audit_path, proposals_path = sys.argv[1], sys.argv[2]

def read_jsonl(p):
    try:
        return [json.loads(ln) for ln in open(p, encoding="utf-8") if ln.strip()]
    except FileNotFoundError:
        return []

audit = read_jsonl(audit_path)
elig = [r for r in audit if r.get("audit_kind") == "eligibility"]
if not elig:
    print("no eligibility audit records -- optimistic-integrate never scored a composite row", file=sys.stderr)
    sys.exit(1)

eligible = [r for r in elig if r.get("outcome") == "eligible" and r.get("decision_basis") == "composite"]
if not eligible:
    outs = sorted({r.get("outcome") for r in elig})
    print(f"no eligible/composite outcome reached the audit; saw outcomes={outs}", file=sys.stderr)
    sys.exit(1)

rec = eligible[0]
# per-signal breakdown must be present and complete (§3.7).
signals = rec.get("signals") or {}
missing = {"confidence", "prevalence", "recency", "novelty"} - set(signals)
if missing:
    print(f"eligible record missing signal breakdown keys: {sorted(missing)}", file=sys.stderr)
    sys.exit(1)
for field in ("score", "threshold", "margin", "weakest_signal", "verified_sessions", "evidence_tier"):
    if field not in rec:
        print(f"eligible record missing field: {field}", file=sys.stderr)
        sys.exit(1)

# the cited proposal must have actually applied (status auto_applied) -- the row
# flowed stamp -> origin gate -> composite -> apply.
proposals = read_jsonl(proposals_path)
applied = [p for p in proposals if p.get("status") == "auto_applied"]
if not applied:
    print("no proposal reached status auto_applied", file=sys.stderr)
    sys.exit(1)

print("PASS: enabled-mode chain reached an ELIGIBLE/composite outcome")
print(f"  proposal={rec.get('proposal_id')} tier={rec.get('evidence_tier')} "
      f"verified_sessions={rec.get('verified_sessions')}")
print(f"  S={rec.get('score'):.4f} (theta={rec.get('threshold')}, margin={rec.get('margin'):+.4f}, "
      f"weakest={rec.get('weakest_signal')})")
print(f"  signals={json.dumps({k: round(v, 4) for k, v in signals.items()}, sort_keys=True)}")
PY

echo "OK: enabled-mode chain smoke proved the composite path (plan.md §8.3 precondition 4)"
