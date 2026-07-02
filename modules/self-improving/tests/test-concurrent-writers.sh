#!/usr/bin/env bash
# Concurrency stress test for the v2 learnings store write path
# (modules/self-improving/lib/learnings_store.py).
#
# Covers:
#   - 8 forked writer PROCESSES (real OS-level concurrency, not just
#     threads) x 50 appends each, spread across 4 agent-ids (2 writers per
#     shard) -- exercises file_locked_append() under genuine contention on
#     shared shard files.
#   - Total line count across all shards matches (no torn/lost writes).
#   - Every line in every shard parses as valid JSON (no interleaved /
#     torn records).
#   - adrev-010: two DIFFERENT agent-ids superseding the SAME live row
#     surfaces conflict:true in the projection (detect-not-prevent -- CAS
#     across shards is TOCTOU; the conflict flag is the real backstop).
#
# All writes go into a fresh CCGM_LEARNINGS_DIR temp dir so the real
# ~/.claude/learnings store is never touched.
#
# Run: bash modules/self-improving/tests/test-concurrent-writers.sh

set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MODULE_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
LIB="${MODULE_ROOT}/lib"

WORKERS=8
APPENDS_PER_WORKER=50
AGENT_COUNT=4

TMP_HOME=$(mktemp -d -t ccgm_learnings_stress.XXXXXX)
export CCGM_LEARNINGS_DIR="${TMP_HOME}/learnings"
export CCGM_LEARNINGS_PROJECT="stress-proj"
trap 'rm -rf "${TMP_HOME}"' EXIT

PASS=0
FAIL=0

assert_eq() {
    local actual="$1"
    local expected="$2"
    local label="$3"
    if [ "${actual}" = "${expected}" ]; then
        PASS=$((PASS + 1))
    else
        FAIL=$((FAIL + 1))
        echo "FAIL: ${label}"
        echo "  expected: ${expected}"
        echo "  actual:   ${actual}"
    fi
}

assert_true() {
    local condition="$1"
    local label="$2"
    if [ "${condition}" = "true" ]; then
        PASS=$((PASS + 1))
    else
        FAIL=$((FAIL + 1))
        echo "FAIL: ${label}"
    fi
}

# ---------------------------------------------------------------------------
# 1. Concurrent writer stress: 8 processes x 50 appends across 4 agent-ids.
# ---------------------------------------------------------------------------

for i in $(seq 0 $((WORKERS - 1))); do
    agent_index=$((i % AGENT_COUNT))
    CCGM_AGENT_ID="agent-${agent_index}" PYTHONPATH="${LIB}" python3 - "${i}" "${APPENDS_PER_WORKER}" <<'PY' &
import sys
import learnings_store as ls

wid, n = int(sys.argv[1]), int(sys.argv[2])
for j in range(n):
    entry = ls.build_entry(
        type_="pattern",
        content=f"stress writer {wid} record {j}",
        tags=[f"writer-{wid}"],
    )
    ls.append_entry(entry)
PY
done
wait

# Every one of the 4 shard files must exist with exactly
# (WORKERS/AGENT_COUNT) * APPENDS_PER_WORKER lines (2 writers per shard).
writers_per_agent=$((WORKERS / AGENT_COUNT))
expected_per_shard=$((writers_per_agent * APPENDS_PER_WORKER))
expected_total=$((WORKERS * APPENDS_PER_WORKER))

total_lines=0
all_valid_json="true"
for a in $(seq 0 $((AGENT_COUNT - 1))); do
    shard="${CCGM_LEARNINGS_DIR}/stress-proj/agents/agent-${a}.jsonl"
    if [ ! -f "${shard}" ]; then
        FAIL=$((FAIL + 1))
        echo "FAIL: shard agent-${a}.jsonl was never created"
        continue
    fi
    count=$(wc -l < "${shard}" | tr -d ' ')
    assert_eq "${count}" "${expected_per_shard}" "agent-${a}.jsonl has ${expected_per_shard} lines (2 writers x ${APPENDS_PER_WORKER})"
    total_lines=$((total_lines + count))

    # Every line must parse as valid JSON (no torn/interleaved records).
    if ! python3 -c "
import json, sys
with open('${shard}') as f:
    for line in f:
        line = line.strip()
        if not line:
            continue
        json.loads(line)
" 2>/dev/null; then
        all_valid_json="false"
        echo "FAIL: agent-${a}.jsonl contains a line that does not parse as JSON"
    fi
done

assert_eq "${total_lines}" "${expected_total}" "total line count across all shards matches ${expected_total}"
assert_true "${all_valid_json}" "every line in every shard parses as JSON"

# ---------------------------------------------------------------------------
# 2. adrev-010: two agent-ids supersede the SAME row -> conflict:true.
# ---------------------------------------------------------------------------

conflict_result=$(PYTHONPATH="${LIB}" python3 <<'PY'
import learnings_store as ls
import os

os.environ.pop("CCGM_AGENT_ID", None)
base = ls.build_entry(type_="pattern", content="contested-by-two-agents")
ls.append_entry(base)
old_id = base["id"]

os.environ["CCGM_AGENT_ID"] = "agent-alpha"
new_a = ls.supersede_entry(old_id, content="alpha's version", slug="stress-proj")

os.environ["CCGM_AGENT_ID"] = "agent-beta"
new_b = ls.supersede_entry(old_id, content="beta's version", slug="stress-proj")

heads = {h["id"]: h for h in ls.load_all("stress-proj")}
conflict = bool(heads.get(old_id, {}).get("conflict"))
both_retained = new_a["id"] in heads and new_b["id"] in heads
print("conflict=%s both_retained=%s" % (conflict, both_retained))
PY
)

echo "${conflict_result}" | grep -q "conflict=True" && PASS=$((PASS + 1)) || { FAIL=$((FAIL + 1)); echo "FAIL: double-supersede across agent-ids did not flag conflict:true (${conflict_result})"; }
echo "${conflict_result}" | grep -q "both_retained=True" && PASS=$((PASS + 1)) || { FAIL=$((FAIL + 1)); echo "FAIL: both competing supersede branches were not retained (${conflict_result})"; }

echo ""
echo "test-concurrent-writers.sh: ${PASS} passed, ${FAIL} failed"
[ "${FAIL}" -eq 0 ] || exit 1
exit 0
