#!/usr/bin/env bash
# Tests for modules/autoheal/bin/autoheal-analyze.sh (Epic 6).
#
# The analyzer talks to the Anthropic Messages API over curl. We never
# call the real API from tests; CCGM_AUTOHEAL_FIXTURE_API_RESPONSE
# replaces the curl response body with a local fixture file.
#
# Coverage:
#   - Happy path: a single day's events produces a proposal that lands
#     in proposals/{today}.jsonl
#   - Prompt log is written (sanity check that the constructed prompt
#     is well-formed and contains the expected runtime context)
#   - 40k token cap rejects an oversized day without crashing
#   - Cost cap honored: a synthesized cost.log at $0.51 short-circuits
#     the run with exit code 2
#   - Calibration window: a never-analyzed install runs in calibration

set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MODULE_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
ANALYZER="${MODULE_ROOT}/bin/autoheal-analyze.sh"
FIXTURE="${SCRIPT_DIR}/fixtures/api-response-sample.json"

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

assert_contains() {
    local haystack="$1"
    local needle="$2"
    local label="$3"
    case "${haystack}" in
        *"${needle}"*)
            PASS=$((PASS + 1))
            ;;
        *)
            FAIL=$((FAIL + 1))
            echo "FAIL: ${label}"
            echo "  expected substring: ${needle}"
            echo "  actual (first 400): ${haystack:0:400}"
            ;;
    esac
}

assert_file_exists() {
    local path="$1"
    local label="$2"
    if [ -f "${path}" ]; then
        PASS=$((PASS + 1))
    else
        FAIL=$((FAIL + 1))
        echo "FAIL: ${label}"
        echo "  expected file: ${path}"
    fi
}

mk_state() {
    local root="$1"
    mkdir -p "${root}/events" "${root}/proposals"
}

write_events() {
    local file="$1"
    local count="$2"
    # Build N synthetic permission_request rows.
    python3 - "${file}" "${count}" <<'PY'
import datetime as dt
import json
import sys

path = sys.argv[1]
count = int(sys.argv[2])

now = dt.datetime.now(dt.timezone.utc)
with open(path, "w", encoding="utf-8") as fh:
    for i in range(count):
        rec = {
            "kind": "permission_request",
            "timestamp": (now - dt.timedelta(minutes=i)).isoformat(),
            "session_id": f"s-{i % 3}",
            "tool_name": "Bash",
            "redacted_command": "git diff --staged",
            "exit_code": None,
            "permission_decision": "ask",
            "cwd": "/tmp/repo",
            "clone_path": "/tmp/repo",
        }
        fh.write(json.dumps(rec) + "\n")
PY
}

# ---------------------------------------------------------------------
# Test 1 — happy path with fixture API response.
# ---------------------------------------------------------------------

T1_HOME=$(mktemp -d -t autoheal_t1.XXXXXX)
trap 'rm -rf "${T1_HOME}"' EXIT
T1_DIR="${T1_HOME}/autoheal"
mk_state "${T1_DIR}"

YESTERDAY=$(python3 -c "import datetime as dt; print((dt.date.today()-dt.timedelta(days=1)).isoformat())")
TODAY=$(python3 -c "import datetime; print(datetime.datetime.now(datetime.timezone.utc).date().isoformat())")
write_events "${T1_DIR}/events/${YESTERDAY}.jsonl" 3

PROMPT_LOG="${T1_HOME}/prompt.log"

env \
    HOME="${T1_HOME}" \
    CCGM_AUTOHEAL_DIR="${T1_DIR}" \
    CCGM_AUTOHEAL_FIXTURE_API_RESPONSE="${FIXTURE}" \
    CCGM_AUTOHEAL_PROMPT_LOG="${PROMPT_LOG}" \
    CCGM_AUTOHEAL_TODAY="${TODAY}" \
    CCGM_AUTOHEAL_CLONE_ID="ccgm-w1-c0" \
    ANTHROPIC_API_KEY="test-not-used-because-fixture" \
    bash "${ANALYZER}" >"${T1_HOME}/run.out" 2>"${T1_HOME}/run.err"
RC=$?

assert_eq "${RC}" "0" "happy path: analyzer exits 0"

PROPOSALS_FILE="${T1_DIR}/proposals/${TODAY}.jsonl"
assert_file_exists "${PROPOSALS_FILE}" "happy path: proposals file created"

assert_file_exists "${PROMPT_LOG}" "happy path: prompt log written"

if [ -f "${PROMPT_LOG}" ]; then
    PL_BODY=$(cat "${PROMPT_LOG}")
    assert_contains "${PL_BODY}" "originating_clone" "prompt log: contains originating_clone"
    assert_contains "${PL_BODY}" "ccgm-w1-c0" "prompt log: contains clone id"
    assert_contains "${PL_BODY}" "calibration_mode" "prompt log: contains calibration_mode"
    assert_contains "${PL_BODY}" "git diff --staged" "prompt log: contains the redacted command from events"
fi

if [ -f "${PROPOSALS_FILE}" ]; then
    LINE_COUNT=$(wc -l < "${PROPOSALS_FILE}" | tr -d ' ')
    assert_eq "${LINE_COUNT}" "1" "happy path: one proposal accepted"
    KIND=$(python3 -c "import json; print(json.loads(open('${PROPOSALS_FILE}').readline())['kind'])")
    assert_eq "${KIND}" "settings_allow_add" "happy path: proposal kind"
    OCLONE=$(python3 -c "import json; print(json.loads(open('${PROPOSALS_FILE}').readline())['originating_clone'])")
    assert_eq "${OCLONE}" "ccgm-w1-c0" "happy path: originating_clone preserved"
fi

# Cost log entry written.
COST_LOG="${T1_DIR}/cost.log"
assert_file_exists "${COST_LOG}" "happy path: cost log written"

# last-analyzed bumped to today.
LAST="${T1_DIR}/last-analyzed"
assert_file_exists "${LAST}" "happy path: last-analyzed written"
if [ -f "${LAST}" ]; then
    LAST_VAL=$(cat "${LAST}")
    assert_eq "${LAST_VAL}" "${TODAY}" "happy path: last-analyzed == today"
fi

# ---------------------------------------------------------------------
# Test 2 — token cap rejection.
#
# Issue #517 raised the default cap from 40k to 200k and made it
# configurable. To trigger the rejection deterministically we set
# max_input_tokens to a tight 5k via config — 1000 friction events
# (permission_request) at ~250 chars each still exceed it even at
# window=0 (no excerpts).
# ---------------------------------------------------------------------

T2_HOME=$(mktemp -d -t autoheal_t2.XXXXXX)
T2_DIR="${T2_HOME}/autoheal"
mk_state "${T2_DIR}"

# Tight cap so 1000 permission_request friction events overflow even at
# window=0. Friction events are kept as full records (they're the
# signal); only routine successes get clustered.
cat > "${T2_DIR}/config.json" <<'EOF'
{
  "max_input_tokens": 5000,
  "daily_cost_cap_usd": 1.00
}
EOF

python3 - "${T2_DIR}/events/${YESTERDAY}.jsonl" 1000 <<'PY'
import datetime as dt
import json
import sys

path = sys.argv[1]
count = int(sys.argv[2])

now = dt.datetime.now(dt.timezone.utc)
with open(path, "w", encoding="utf-8") as fh:
    for i in range(count):
        rec = {
            "kind": "permission_request",
            # `permission_decision: "ask"` keeps these as friction
            # post-fix (issue #519); friction events are NOT clustered,
            # so 1000 of them at ~250 chars each genuinely overflow the
            # tight 5K cap even at window=0. Without the decision field
            # the events would cluster down to a single record and the
            # cap would never be hit.
            "permission_decision": "ask",
            "timestamp": (now - dt.timedelta(seconds=i)).isoformat(),
            "session_id": f"s-{i}",
            "tool_name": "Bash",
            "redacted_command": "git " + ("x" * 220),
            "cwd": "/tmp/repo",
        }
        fh.write(json.dumps(rec) + "\n")
PY

env \
    HOME="${T2_HOME}" \
    CCGM_AUTOHEAL_DIR="${T2_DIR}" \
    CCGM_AUTOHEAL_FIXTURE_API_RESPONSE="${FIXTURE}" \
    CCGM_AUTOHEAL_TODAY="${TODAY}" \
    ANTHROPIC_API_KEY="x" \
    bash "${ANALYZER}" >"${T2_HOME}/run.out" 2>"${T2_HOME}/run.err"
RC=$?

# The analyzer rejects the day but continues; overall rc=0 unless other
# days fail. With a single oversize day, rc=0 and the proposals file is
# either absent or empty.
assert_eq "${RC}" "0" "token cap: analyzer exits 0 (rejects day, continues)"

if [ -f "${T2_DIR}/proposals/${TODAY}.jsonl" ]; then
    SIZE=$(wc -c < "${T2_DIR}/proposals/${TODAY}.jsonl" | tr -d ' ')
    assert_eq "${SIZE}" "0" "token cap: no proposals on oversize day"
fi

ERR_BODY=$(cat "${T2_HOME}/run.err")
assert_contains "${ERR_BODY}" "estimated input tokens" "token cap: warning printed to stderr"

# Issue #517: rejected day must be logged AND last-analyzed must NOT
# advance past it (so the next run with a higher cap retries it).
assert_file_exists "${T2_DIR}/rejected-days.jsonl" "token cap: rejection logged to rejected-days.jsonl"

if [ -f "${T2_DIR}/rejected-days.jsonl" ]; then
    REJ_DATE=$(python3 -c "
import json
with open('${T2_DIR}/rejected-days.jsonl') as fh:
    for line in fh:
        line = line.strip()
        if not line:
            continue
        rec = json.loads(line)
        print(rec.get('date',''))
        break
")
    assert_eq "${REJ_DATE}" "${YESTERDAY}" "token cap: rejected-days.jsonl records the right date"
fi

LAST_VAL=""
if [ -f "${T2_DIR}/last-analyzed" ]; then
    LAST_VAL=$(cat "${T2_DIR}/last-analyzed" | tr -d '\n')
fi
# last-analyzed must be < rejected day (so next run will retry it).
if [ -n "${LAST_VAL}" ]; then
    if [ "${LAST_VAL}" \< "${YESTERDAY}" ]; then
        PASS=$((PASS + 1))
    else
        FAIL=$((FAIL + 1))
        echo "FAIL: token cap: last-analyzed should be < rejected day ${YESTERDAY}, got ${LAST_VAL}"
    fi
fi

# ---------------------------------------------------------------------
# Test 3 — daily cost cap honored.
# ---------------------------------------------------------------------

T3_HOME=$(mktemp -d -t autoheal_t3.XXXXXX)
T3_DIR="${T3_HOME}/autoheal"
mk_state "${T3_DIR}"
write_events "${T3_DIR}/events/${YESTERDAY}.jsonl" 3

# Issue #517 raised the default cost cap to $1.00. Pin the test to its
# original $0.50 cap via config so the synthesized $0.51 cost.log line
# still triggers a skip — keeps the test about cost-cap mechanics, not
# default values.
cat > "${T3_DIR}/config.json" <<'EOF'
{
  "daily_cost_cap_usd": 0.50
}
EOF

# Synthesize a cost.log near the limit (51 cents today).
printf '%s\t100000\t5000\t0.510000\n' "${TODAY}" > "${T3_DIR}/cost.log"

env \
    HOME="${T3_HOME}" \
    CCGM_AUTOHEAL_DIR="${T3_DIR}" \
    CCGM_AUTOHEAL_FIXTURE_API_RESPONSE="${FIXTURE}" \
    CCGM_AUTOHEAL_TODAY="${TODAY}" \
    ANTHROPIC_API_KEY="x" \
    bash "${ANALYZER}" >"${T3_HOME}/run.out" 2>"${T3_HOME}/run.err"
RC=$?

assert_eq "${RC}" "2" "cost cap: analyzer exits 2 when over cap"

if [ -f "${T3_DIR}/proposals/${TODAY}.jsonl" ]; then
    SIZE=$(wc -c < "${T3_DIR}/proposals/${TODAY}.jsonl" | tr -d ' ')
    assert_eq "${SIZE}" "0" "cost cap: no proposals written when capped"
fi

CC_ERR=$(cat "${T3_HOME}/run.err")
assert_contains "${CC_ERR}" "daily cost cap reached" "cost cap: stderr explains the skip"

# ---------------------------------------------------------------------
# Test 4 — calibration window math: fresh install means calibration on.
# ---------------------------------------------------------------------

T4_HOME=$(mktemp -d -t autoheal_t4.XXXXXX)
T4_DIR="${T4_HOME}/autoheal"
mk_state "${T4_DIR}"
write_events "${T4_DIR}/events/${YESTERDAY}.jsonl" 3

CAL_PROMPT="${T4_HOME}/cal-prompt.log"

env \
    HOME="${T4_HOME}" \
    CCGM_AUTOHEAL_DIR="${T4_DIR}" \
    CCGM_AUTOHEAL_FIXTURE_API_RESPONSE="${FIXTURE}" \
    CCGM_AUTOHEAL_PROMPT_LOG="${CAL_PROMPT}" \
    CCGM_AUTOHEAL_TODAY="${TODAY}" \
    ANTHROPIC_API_KEY="x" \
    bash "${ANALYZER}" >"${T4_HOME}/run.out" 2>"${T4_HOME}/run.err"
RC=$?

assert_eq "${RC}" "0" "calibration: analyzer exits 0"

if [ -f "${CAL_PROMPT}" ]; then
    CAL_BODY=$(cat "${CAL_PROMPT}")
    # A fresh install has no last-analyzed file — mtime-based check
    # cannot fire — we conservatively return calibration_mode=true.
    assert_contains "${CAL_BODY}" "\"calibration_mode\": true" "calibration: prompt encodes calibration_mode=true on fresh install"
fi

# ---------------------------------------------------------------------
# Test 5 — graceful skip when ANTHROPIC_API_KEY absent and no fixture.
# ---------------------------------------------------------------------

T5_HOME=$(mktemp -d -t autoheal_t5.XXXXXX)
T5_DIR="${T5_HOME}/autoheal"
mk_state "${T5_DIR}"
write_events "${T5_DIR}/events/${YESTERDAY}.jsonl" 1

# Unset ANTHROPIC_API_KEY in a subshell rather than passing -u to env
# (GNU env supports it but BSD env on macOS does not).
(
    unset ANTHROPIC_API_KEY
    export HOME="${T5_HOME}"
    export CCGM_AUTOHEAL_DIR="${T5_DIR}"
    export CCGM_AUTOHEAL_TODAY="${TODAY}"
    bash "${ANALYZER}" >"${T5_HOME}/run.out" 2>"${T5_HOME}/run.err"
)
RC=$?

assert_eq "${RC}" "0" "no API key: analyzer exits 0 gracefully"
NK_ERR=$(cat "${T5_HOME}/run.err")
assert_contains "${NK_ERR}" "ANTHROPIC_API_KEY not set" "no API key: stderr explains the skip"

# ---------------------------------------------------------------------
# Test 6 — rejection log + cost log use locked appends (issue #503).
# log_rejection and append_cost must route through the same fcntl.flock
# path as append_jsonl so concurrent clones cannot tear writes. Guard
# the property at the source level.
# ---------------------------------------------------------------------

ANALYZER_SRC=$(cat "${ANALYZER}")
assert_contains "${ANALYZER_SRC}" "fcntl.flock" "locked-append: analyzer uses fcntl.flock"
assert_contains "${ANALYZER_SRC}" "append_locked(path" "locked-append: log_rejection/append_cost route through append_locked"

# ---------------------------------------------------------------------
# Test 7 — per-model cost pricing (issue #497).
# Fixture usage block is {input: 1200, output: 240}. Verify:
#   - sonnet default config -> $3/M in + $15/M out
#       cost = (1200*3 + 240*15) / 1e6 = (3600 + 3600) / 1e6 = 0.007200
#   - opus default_model -> $15/M in + $75/M out
#       cost = (1200*15 + 240*75) / 1e6 = (18000 + 18000) / 1e6 = 0.036000
#   - unknown model -> stderr warning + sonnet fallback (0.007200)
#   - cost.log lines include the model id as the 5th tab-separated field
# ---------------------------------------------------------------------

write_config() {
    # write_config <path> <default_model> [include_pricing]
    local path="$1"
    local default_model="$2"
    local include_pricing="${3:-1}"
    mkdir -p "$(dirname "${path}")"
    if [ "${include_pricing}" = "1" ]; then
        cat > "${path}" <<EOF
{
  "default_model": "${default_model}",
  "cost_pricing": {
    "claude-sonnet-4-6":  {"input_per_million": 3,    "output_per_million": 15},
    "claude-opus-4-7":    {"input_per_million": 15,   "output_per_million": 75},
    "claude-haiku-4-5":   {"input_per_million": 0.80, "output_per_million": 4}
  }
}
EOF
    else
        cat > "${path}" <<EOF
{
  "default_model": "${default_model}"
}
EOF
    fi
}

read_cost_field() {
    # read_cost_field <cost.log path> <today> <0-based field index>
    python3 - "$1" "$2" "$3" <<'PY'
import sys
path, today, idx = sys.argv[1], sys.argv[2], int(sys.argv[3])
with open(path, "r", encoding="utf-8") as fh:
    for line in fh:
        line = line.rstrip("\n")
        if not line:
            continue
        parts = line.split("\t")
        if parts and parts[0] == today:
            print(parts[idx] if idx < len(parts) else "")
            break
PY
}

# Test 7a — sonnet default pricing.
T7A_HOME=$(mktemp -d -t autoheal_t7a.XXXXXX)
T7A_DIR="${T7A_HOME}/autoheal"
mk_state "${T7A_DIR}"
write_events "${T7A_DIR}/events/${YESTERDAY}.jsonl" 1
write_config "${T7A_DIR}/config.json" "claude-sonnet-4-6"

env \
    HOME="${T7A_HOME}" \
    CCGM_AUTOHEAL_DIR="${T7A_DIR}" \
    CCGM_AUTOHEAL_FIXTURE_API_RESPONSE="${FIXTURE}" \
    CCGM_AUTOHEAL_TODAY="${TODAY}" \
    ANTHROPIC_API_KEY="x" \
    bash "${ANALYZER}" >"${T7A_HOME}/run.out" 2>"${T7A_HOME}/run.err"
RC=$?
assert_eq "${RC}" "0" "pricing sonnet: analyzer exits 0"

T7A_COST_VAL=$(read_cost_field "${T7A_DIR}/cost.log" "${TODAY}" 3)
assert_eq "${T7A_COST_VAL}" "0.007200" "pricing sonnet: cost matches \$3/M + \$15/M"
T7A_MODEL_VAL=$(read_cost_field "${T7A_DIR}/cost.log" "${TODAY}" 4)
assert_eq "${T7A_MODEL_VAL}" "claude-sonnet-4-6" "pricing sonnet: model id recorded in cost.log"

T7A_ERR=$(cat "${T7A_HOME}/run.err")
case "${T7A_ERR}" in
    *"no cost_pricing"*)
        FAIL=$((FAIL + 1))
        echo "FAIL: pricing sonnet: should not emit unknown-model warning"
        ;;
    *)
        PASS=$((PASS + 1))
        ;;
esac

# Test 7b — opus default_model uses opus pricing.
T7B_HOME=$(mktemp -d -t autoheal_t7b.XXXXXX)
T7B_DIR="${T7B_HOME}/autoheal"
mk_state "${T7B_DIR}"
write_events "${T7B_DIR}/events/${YESTERDAY}.jsonl" 1
write_config "${T7B_DIR}/config.json" "claude-opus-4-7"

env \
    HOME="${T7B_HOME}" \
    CCGM_AUTOHEAL_DIR="${T7B_DIR}" \
    CCGM_AUTOHEAL_FIXTURE_API_RESPONSE="${FIXTURE}" \
    CCGM_AUTOHEAL_TODAY="${TODAY}" \
    ANTHROPIC_API_KEY="x" \
    bash "${ANALYZER}" >"${T7B_HOME}/run.out" 2>"${T7B_HOME}/run.err"
RC=$?
assert_eq "${RC}" "0" "pricing opus: analyzer exits 0"

T7B_COST_VAL=$(read_cost_field "${T7B_DIR}/cost.log" "${TODAY}" 3)
assert_eq "${T7B_COST_VAL}" "0.036000" "pricing opus: cost matches \$15/M + \$75/M"
T7B_MODEL_VAL=$(read_cost_field "${T7B_DIR}/cost.log" "${TODAY}" 4)
assert_eq "${T7B_MODEL_VAL}" "claude-opus-4-7" "pricing opus: model id recorded in cost.log"

# Test 7c — unknown model falls back to sonnet pricing AND warns.
T7C_HOME=$(mktemp -d -t autoheal_t7c.XXXXXX)
T7C_DIR="${T7C_HOME}/autoheal"
mk_state "${T7C_DIR}"
write_events "${T7C_DIR}/events/${YESTERDAY}.jsonl" 1
write_config "${T7C_DIR}/config.json" "claude-mystery-9-9"

env \
    HOME="${T7C_HOME}" \
    CCGM_AUTOHEAL_DIR="${T7C_DIR}" \
    CCGM_AUTOHEAL_FIXTURE_API_RESPONSE="${FIXTURE}" \
    CCGM_AUTOHEAL_TODAY="${TODAY}" \
    ANTHROPIC_API_KEY="x" \
    bash "${ANALYZER}" >"${T7C_HOME}/run.out" 2>"${T7C_HOME}/run.err"
RC=$?
assert_eq "${RC}" "0" "pricing unknown: analyzer exits 0"

T7C_COST_VAL=$(read_cost_field "${T7C_DIR}/cost.log" "${TODAY}" 3)
# The last-resort rate tracks the model the analyzer actually calls
# (claude-sonnet-5, $2/M in + $10/M out since #1028), not the retired pin:
#   (1200*2 + 240*10) / 1e6 = (2400 + 2400) / 1e6 = 0.004800
assert_eq "${T7C_COST_VAL}" "0.004800" "pricing unknown: cost falls back to the analyzer's own model (\$2/M + \$10/M)"
T7C_MODEL_VAL=$(read_cost_field "${T7C_DIR}/cost.log" "${TODAY}" 4)
assert_eq "${T7C_MODEL_VAL}" "claude-mystery-9-9" "pricing unknown: configured model id still recorded for traceability"

T7C_ERR=$(cat "${T7C_HOME}/run.err")
assert_contains "${T7C_ERR}" "no cost_pricing for model claude-mystery-9-9" "pricing unknown: stderr warning emitted"
assert_contains "${T7C_ERR}" "falling back to claude-sonnet-5" "pricing unknown: stderr names the model it fell back to"

# Test 7d — back-compat: a cost.log written by older code (no model
# field) parses cleanly when summing today's spend (cap check).
T7D_HOME=$(mktemp -d -t autoheal_t7d.XXXXXX)
T7D_DIR="${T7D_HOME}/autoheal"
mk_state "${T7D_DIR}"
write_events "${T7D_DIR}/events/${YESTERDAY}.jsonl" 1
# Legacy 4-field line (no model). Sum is 0.40, well below the 50c cap so
# the analyzer must proceed. If today_cost_cents() crashes on a missing
# 5th field, the analyzer exits 1 instead of 0.
printf '%s\t100000\t5000\t0.400000\n' "${TODAY}" > "${T7D_DIR}/cost.log"

env \
    HOME="${T7D_HOME}" \
    CCGM_AUTOHEAL_DIR="${T7D_DIR}" \
    CCGM_AUTOHEAL_FIXTURE_API_RESPONSE="${FIXTURE}" \
    CCGM_AUTOHEAL_TODAY="${TODAY}" \
    ANTHROPIC_API_KEY="x" \
    bash "${ANALYZER}" >"${T7D_HOME}/run.out" 2>"${T7D_HOME}/run.err"
RC=$?
assert_eq "${RC}" "0" "pricing back-compat: legacy 4-field cost.log still parses"

# After the run, a new 5-field line should sit alongside the legacy one.
LEGACY_LINE_COUNT=$(grep -c "^${TODAY}" "${T7D_DIR}/cost.log" || true)
if [ "${LEGACY_LINE_COUNT}" -ge 2 ]; then
    PASS=$((PASS + 1))
else
    FAIL=$((FAIL + 1))
    echo "FAIL: pricing back-compat: expected legacy + new cost.log lines, got ${LEGACY_LINE_COUNT}"
fi

# Cleanup test 7 dirs.
for d in "${T7A_HOME}" "${T7B_HOME}" "${T7C_HOME}" "${T7D_HOME}"; do
    rm -rf "${d}"
done

# ---------------------------------------------------------------------
# Test 8 — request shape on the wire (#1026, #1028).
#
# The fixture path short-circuits curl, so this test shims curl on PATH
# instead: the shim keeps the real request body the analyzer built and
# answers with the same fixture. Every field checked here belongs in the
# body; none of them is a header.
# ---------------------------------------------------------------------

T8_HOME=$(mktemp -d -t autoheal_t8.XXXXXX)
T8_DIR="${T8_HOME}/autoheal"
mk_state "${T8_DIR}"
write_events "${T8_DIR}/events/${YESTERDAY}.jsonl" 3

T8_BIN="${T8_HOME}/bin"
mkdir -p "${T8_BIN}"
cat > "${T8_BIN}/curl" <<EOF
#!/usr/bin/env bash
# Capture the request body, then answer with the fixture.
prev=""
for arg in "\$@"; do
    case "\${arg}" in
        --data-binary)
            prev="databinary"
            ;;
        @*)
            if [ "\${prev}" = "databinary" ]; then
                cp "\${arg#@}" "${T8_HOME}/request.json"
            fi
            prev=""
            ;;
        *)
            prev=""
            ;;
    esac
done
cat "${FIXTURE}"
EOF
chmod +x "${T8_BIN}/curl"

env \
    HOME="${T8_HOME}" \
    PATH="${T8_BIN}:${PATH}" \
    CCGM_AUTOHEAL_DIR="${T8_DIR}" \
    CCGM_AUTOHEAL_TODAY="${TODAY}" \
    ANTHROPIC_API_KEY="sk-test-not-a-real-key" \
    bash "${ANALYZER}" >"${T8_HOME}/run.out" 2>"${T8_HOME}/run.err"
RC=$?
assert_eq "${RC}" "0" "request shape: analyzer exits 0 against the capturing curl shim"
assert_file_exists "${T8_HOME}/request.json" "request shape: request body captured"

if [ -f "${T8_HOME}/request.json" ]; then
    REQ_CHECK=$(python3 - "${T8_HOME}/request.json" "${MODULE_ROOT}/lib/proposal-schema.json" <<'PY'
import json
import sys

body = json.load(open(sys.argv[1], encoding="utf-8"))
proposal_schema = json.load(open(sys.argv[2], encoding="utf-8"))
problems = []


def want(label, actual, expected):
    if actual != expected:
        problems.append(f"{label}: expected {expected!r}, got {actual!r}")


want("model", body.get("model"), "claude-sonnet-5")
want("max_tokens", body.get("max_tokens"), 16000)
want("thinking", body.get("thinking"), {"type": "disabled"})

oc = body.get("output_config") or {}
want("effort", oc.get("effort"), "low")
fmt = oc.get("format") or {}
want("format.type", fmt.get("type"), "json_schema")

schema = fmt.get("schema") or {}
want("schema.required", schema.get("required"), ["proposals"])
want("schema.additionalProperties", schema.get("additionalProperties"), False)
item = ((schema.get("properties") or {}).get("proposals") or {}).get("items") or {}
want("item.additionalProperties", item.get("additionalProperties"), False)

# The offered fields are exactly proposal-schema.json's own required set,
# so what the model is held to and what the post-parse check validates
# cannot drift apart.
want("item.required", sorted(item.get("required", [])), sorted(proposal_schema.get("required", [])))
want("item.properties", sorted(item.get("properties", {})), sorted(proposal_schema.get("required", [])))

# Bounds the structured-outputs subset rejects must not survive.
banned = {"minimum", "maximum", "multipleOf", "minLength", "maxLength",
          "minItems", "maxItems", "uniqueItems", "pattern", "default"}


def walk(node):
    if isinstance(node, dict):
        yield node
        for value in node.values():
            yield from walk(value)
    elif isinstance(node, list):
        for value in node:
            yield from walk(value)


for node in walk(schema):
    for keyword in sorted(banned & set(node)):
        problems.append(f"unsupported schema keyword survived: {keyword}")

print("OK" if not problems else "; ".join(problems))
PY
)
    assert_eq "${REQ_CHECK}" "OK" "request shape: model, cap, thinking, effort, and output schema are all as specified"

    # None of the output-contract fields travels as a header.
    assert_contains "$(grep -- '-H "' "${ANALYZER}" | tr -d '\n')" "anthropic-version" "request shape: headers are auth/version/content-type only"
    for banned_hdr in "thinking" "effort" "output_config" "json_schema"; do
        if grep -- '-H "' "${ANALYZER}" | grep -q "${banned_hdr}"; then
            FAIL=$((FAIL + 1))
            echo "FAIL: request shape: ${banned_hdr} must not be sent as a header"
        else
            PASS=$((PASS + 1))
        fi
    done
fi

# Test 8b — a response that stopped at the output cap is reported as a
# failed extraction, not a quiet zero-proposal day (#1026).
T8B_HOME=$(mktemp -d -t autoheal_t8b.XXXXXX)
T8B_DIR="${T8B_HOME}/autoheal"
mk_state "${T8B_DIR}"
write_events "${T8B_DIR}/events/${YESTERDAY}.jsonl" 3

TRUNCATED_FIXTURE="${T8B_HOME}/truncated-response.json"
python3 - "${FIXTURE}" "${TRUNCATED_FIXTURE}" <<'PY'
import json
import sys

resp = json.load(open(sys.argv[1], encoding="utf-8"))
resp["stop_reason"] = "max_tokens"
with open(sys.argv[2], "w", encoding="utf-8") as fh:
    json.dump(resp, fh)
PY

env \
    HOME="${T8B_HOME}" \
    CCGM_AUTOHEAL_DIR="${T8B_DIR}" \
    CCGM_AUTOHEAL_FIXTURE_API_RESPONSE="${TRUNCATED_FIXTURE}" \
    CCGM_AUTOHEAL_TODAY="${TODAY}" \
    ANTHROPIC_API_KEY="x" \
    bash "${ANALYZER}" >"${T8B_HOME}/run.out" 2>"${T8B_HOME}/run.err"
RC=$?
assert_eq "${RC}" "0" "truncation: analyzer still exits 0 (the day is reported, not fatal)"
T8B_ERR=$(cat "${T8B_HOME}/run.err")
assert_contains "${T8B_ERR}" "stop_reason=max_tokens" "truncation: stderr names the cap stop and the day"
T8B_OUT=$(cat "${T8B_HOME}/run.out")
assert_contains "${T8B_OUT}" '"truncated": 1' "truncation: the per-day summary carries the count"

# Test 8c — the fence stripper is gone; a fenced body is a failure now.
assert_contains "${ANALYZER_SRC}" "structured outputs" "no fence stripper: parse_proposals documents why it does not strip"
case "${ANALYZER_SRC}" in
    *'Strip an optional code fence'*)
        FAIL=$((FAIL + 1))
        echo "FAIL: no fence stripper: the code-fence stripping branch must be gone (#1028)"
        ;;
    *)
        PASS=$((PASS + 1))
        ;;
esac

for d in "${T8_HOME}" "${T8B_HOME}"; do
    rm -rf "${d}"
done

# ---------------------------------------------------------------------
# Summary.
# ---------------------------------------------------------------------

echo ""
echo "test-analyzer-api-call.sh: ${PASS} passed, ${FAIL} failed"
[ "${FAIL}" -eq 0 ] || exit 1
exit 0
