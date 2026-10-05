#!/usr/bin/env bash
# test-metrics.sh
#
# lib/autoheal_metrics.py computes the RCA section 3.8 success metrics that the
# data supports today and marks the rest not computable (#1099 item 4.3).
# Reads a fixture directory; the real ~/.claude/autoheal is never touched.
#
# Run: bash modules/autoheal/tests/test-metrics.sh

set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MODULE_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
METRICS="${MODULE_ROOT}/lib/autoheal_metrics.py"

PASS=0
FAIL=0
assert_eq() {
    if [ "$1" = "$2" ]; then
        PASS=$((PASS + 1))
    else
        FAIL=$((FAIL + 1))
        echo "FAIL: $3"
        echo "  expected: $2"
        echo "  actual:   $1"
    fi
}

TMP="$(mktemp -d -t autoheal-metrics-test.XXXXXX)"
trap 'rm -rf "${TMP}"' EXIT
AH="${TMP}/ah"
NOW="2026-10-04T12:00:00Z"

# m <metric id> <python expression over d>
run() { CCGM_AUTOHEAL_DIR="${AH}" python3 "${METRICS}" --now "${NOW}" > "${TMP}/out.json" 2>"${TMP}/err"; }
m() {
    python3 -c "import json; d={x['id']: x for x in json.load(open('${TMP}/out.json'))['metrics']}['$1']; print($2)"
}

# 1. Empty directory: the four computable metrics say so, nothing crashes.
mkdir -p "${AH}"
run
assert_eq "$?" "0" "empty: exit 0"
for id in run_health_30d acceptance_rate applied_effective monthly_spend_usd; do
    assert_eq "$(m ${id} "d['status']")" "not_computable" "empty: ${id} not computable"
    assert_eq "$(m ${id} "d['value']")" "None" "empty: ${id} has no value"
done
for id in time_to_detect friction_rate cost_per_accepted; do
    assert_eq "$(m ${id} "d['status']")" "not_computable" "always: ${id} not computable"
done

# 2. Run health. First run 2026-09-30 (5 days to 10-04): ok, ok, failed then ok on the
#    same day (the last run wins), paused, ok. Paused is left out: 3 ok of 4 days.
cat > "${AH}/health-history.jsonl" <<'EOF'
{"date": "2026-09-30", "status": "ok", "generated_at": "2026-09-30T08:00:00Z"}
{"date": "2026-10-01", "status": "ok", "generated_at": "2026-10-01T08:00:00Z"}
{"date": "2026-10-02", "status": "failed", "generated_at": "2026-10-02T08:00:00Z"}
{"date": "2026-10-02", "status": "ok", "generated_at": "2026-10-02T09:00:00Z"}
{"date": "2026-10-03", "status": "paused", "generated_at": "2026-10-03T08:00:00Z"}
{"date": "2026-10-04", "status": "failed", "generated_at": "2026-10-04T08:00:00Z"}
{"date": "2026-01-01", "status": "failed", "generated_at": "2026-01-01T08:00:00Z"}
EOF
run
assert_eq "$(m run_health_30d "d['value']")" "0.75" "run health: 3 ok of 4 counted days; later run wins; paused and old rows left out"
assert_eq "$(m run_health_30d "d['status']")" "missed" "run health: 75% misses the 95% target"
assert_eq "$(m run_health_30d "'1 paused' in d['detail'] or '1 paused day' in d['detail']")" "True" "run health: detail names the paused day"
printf '{"date": "2026-10-04", "status": "ok", "generated_at": "2026-10-04T09:00:00Z"}\n' > "${AH}/health-history.jsonl"
run
assert_eq "$(m run_health_30d "[d['value'], d['status']]")" "[1.0, 'met']" "run health: one ok day is met"
printf '{"date": "2026-10-04", "status": "paused"}\n' > "${AH}/health-history.jsonl"
run
assert_eq "$(m run_health_30d "d['status']")" "not_computable" "run health: only paused days is not computable"

# 3. Acceptance and effectiveness from the ledger. Auto-applied rows are not a decision.
cat > "${AH}/proposals.jsonl" <<'EOF'
{"id": "a1", "state": "applied"}
{"id": "a2", "state": "measured", "outcome": "effective"}
{"id": "a3", "state": "measured", "outcome": "ineffective"}
{"id": "a4", "state": "reverted", "outcome": "harmful"}
{"id": "a5", "state": "measured", "outcome": "unmeasurable"}
{"id": "a6", "state": "measured", "outcome": "effective", "applied_by": "auto"}
{"id": "r1", "state": "rejected"}
{"id": "r2", "state": "rejected"}
{"id": "s1", "state": "snoozed"}
{"id": "d1", "state": "dropped"}
EOF
run
assert_eq "$(m acceptance_rate "[d['value'], d['status']]")" "[0.714, 'met']" "acceptance: 5 accepted of 7 decided; auto, snoozed and dropped left out"
assert_eq "$(m applied_effective "[d['value'], d['status']]")" "[0.5, 'missed']" "effective: 2 of 4 rated (unmeasurable left out) misses 60%"
cat > "${AH}/proposals.jsonl" <<'EOF'
{"id": "a1", "state": "applied"}
{"id": "r1", "state": "rejected"}
{"id": "r2", "state": "rejected"}
{"id": "r3", "state": "rejected"}
EOF
run
assert_eq "$(m acceptance_rate "d['status']")" "missed" "acceptance: 1 of 4 misses 40%"
assert_eq "$(m applied_effective "d['status']")" "not_computable" "effective: no measured fix is not computable"

# 4. Spend: only the last 30 days (2026-09-05 through 10-04) count.
printf '2026-05-19\t164877\t1388\t0.515451\tclaude-sonnet-4-6\n2026-09-04\t1\t1\t50.000000\tm\n2026-09-05\t10\t5\t1.250000\tm\n2026-10-04\t10\t5\t0.500000\tm\nbroken row\n' > "${AH}/cost.log"
run
assert_eq "$(m monthly_spend_usd "[d['value'], d['status']]")" "[1.75, 'met']" "spend: 30-day window only, malformed row skipped"
printf '2026-10-04\t10\t5\t3.500000\tm\n' > "${AH}/cost.log"
run
assert_eq "$(m monthly_spend_usd "d['status']")" "missed" "spend: \$3.50 misses the \$3 target"
printf '2026-05-19\t1\t1\t0.500000\tm\n' > "${AH}/cost.log"
run
assert_eq "$(m monthly_spend_usd "[d['value'], d['status']]")" "[0.0, 'met']" "spend: history but none in the window is \$0"

echo ""
echo "test-metrics.sh: ${PASS} passed, ${FAIL} failed"
[ "${FAIL}" -eq 0 ]
