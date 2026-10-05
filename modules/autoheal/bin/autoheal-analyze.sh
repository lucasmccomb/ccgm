#!/usr/bin/env bash
# CCGM autoheal - daily analyzer (#1099 Phase 2.2).
#
# Counting is code, drafting is the model. The flow:
#
#   1. bin/autoheal-aggregate.py --date <day> counts recurring failures over a
#      14-day window with no model call and writes signatures/<day>.json.
#   2. lib/draft_proposals.py plan takes at most 3 qualifying signatures.
#        - A hook-denial signature becomes an `issue` proposal, drafted
#          locally. It never goes to the model, and nothing is filed on GitHub.
#        - Any other signature becomes a ~6-12k-token request: the signature,
#          the module index, the full text of at most 2 candidate rule files
#          and at most one redacted 1,500-character excerpt.
#   3. No qualifying signature means no API call: log it and exit 0.
#   4. For each request this script measures the input with the Anthropic
#      count_tokens endpoint (free) and refuses to send more than 15k tokens.
#   5. It sends the request to the Messages API, logs the cost, and checks
#      stop_reason. The model answers with a rule_insert or a skip.
#   6. lib/draft_proposals.py finish checks the answer against the real file
#      (target is a candidate, anchor heading exists), builds the unified diff
#      and appends the proposal row to the ledger, proposals.jsonl. A failed check
#      drops the answer with a counted reason (anchor_missing,
#      path_not_candidate, ...).
#
# A failed call is logged and counted, never retried in the run and never held
# for a later one: the aggregator's coverage check, not a day watermark,
# decides what gets drafted next.
#
# Why curl and not `claude -p`: no nested-tool runtime means no process-exec
# attack surface. The analyzer is a pure prompt -> JSON pipeline.
#
# Env vars:
#   ANTHROPIC_API_KEY            Required for a model call (hook-denial issues
#                                 and the no-qualifying-signature exit need
#                                 none). Read from the shell env at run time;
#                                 never baked into the launchd plist.
#   CCGM_AUTOHEAL_DIR            Root of autoheal state (default
#                                 ~/.claude/autoheal). Tests override.
#   CCGM_AUTOHEAL_LEDGER         Proposal ledger (default $CCGM_AUTOHEAL_DIR/proposals.jsonl).
#   CCGM_AUTOHEAL_CONFIG         Config JSON (default $CCGM_AUTOHEAL_DIR/config.json).
#                                 Keys read here: default_model, model,
#                                 daily_cost_cap_usd, cost_pricing,
#                                 ccgm_repo_path (see lib/module-index.py).
#   CCGM_AUTOHEAL_ANALYZER_PROMPT Override path for the prompt
#                                 (default <module>/lib/analyzer-prompt.md).
#   CCGM_AUTOHEAL_API_URL        Messages endpoint (default
#                                 https://api.anthropic.com/v1/messages). The
#                                 count_tokens URL is this plus /count_tokens.
#   CCGM_AUTOHEAL_PROMPT_LOG     If set, each constructed prompt is appended
#                                 here for inspection. Tests only.
#   CCGM_AUTOHEAL_TODAY          YYYY-MM-DD override for "today" (UTC).
#   CCGM_AUTOHEAL_CLONE_ID       Originating clone label (default cwd basename).
#   USE_ANALYZER_SANDBOX         If 1 and sandbox-exec exists, wraps curl in
#                                 the seatbelt profile.
#
# CLI flags:
#   --date YYYY-MM-DD            Window end for the aggregator (default today UTC).
#   --help                       Print usage and exit.
#
# Exit codes:
#   0  success, including "nothing qualified" and "drafting skipped"
#   1  fatal setup error, or at least one call failed or was refused
#   2  daily cost cap reached, or the configured model cannot do structured outputs
#
# Invoked by `autoheal-daily.sh`; also runnable standalone.

set -u
set -o pipefail

# ---------------------------------------------------------------------
# CLI parsing.
# ---------------------------------------------------------------------

DATE_ARG=""
while [ "$#" -gt 0 ]; do
    case "$1" in
        --date)
            shift
            if [ "$#" -eq 0 ]; then
                echo "autoheal-analyze: --date requires YYYY-MM-DD" >&2
                exit 1
            fi
            DATE_ARG="$1"
            shift
            ;;
        --date=*)
            DATE_ARG="${1#--date=}"
            shift
            ;;
        --help|-h)
            cat <<'USAGE'
Usage: autoheal-analyze.sh [--date YYYY-MM-DD]

Daily autoheal analyzer. Aggregates recurring tool failures over a 14-day
window ending at --date (default: today, UTC), then drafts a small rule
proposal for each of the top 3 qualifying signatures. With no qualifying
signature it makes no API call.

Options:
  --date YYYY-MM-DD   Window end for the aggregator.
  --help              Show this message.

See modules/autoheal/bin/autoheal-analyze.sh for env-var docs.
USAGE
            exit 0
            ;;
        *)
            echo "autoheal-analyze: unknown argument: $1" >&2
            echo "Run with --help for usage." >&2
            exit 1
            ;;
    esac
done

if [ -n "${DATE_ARG}" ]; then
    if ! python3 -c "import datetime as dt, sys; dt.date.fromisoformat(sys.argv[1])" "${DATE_ARG}" 2>/dev/null; then
        echo "autoheal-analyze: --date value '${DATE_ARG}' is not a valid YYYY-MM-DD date" >&2
        exit 1
    fi
fi

# ---------------------------------------------------------------------
# Resolve module paths.
# ---------------------------------------------------------------------

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MODULE_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

# ---------------------------------------------------------------------
# Tunables.
#
# INPUT_TOKEN_LIMIT is a hard cap, not a config knob: a request that
# count_tokens measures above it is refused unsent. Installs seeded before
# #1099 carry a 200000-token input cap in config.json; it is ignored.
#
# Daily cost cap default: $10.00 in cents (issue #529).
# ---------------------------------------------------------------------

INPUT_TOKEN_LIMIT=15000
DAILY_COST_CAP_CENTS_DEFAULT=1000
DAILY_COST_CAP_CENTS="${DAILY_COST_CAP_CENTS_DEFAULT}"
# Sonnet 5 since #1028: Sonnet 4.6 does not support structured outputs, which
# the drafting answer relies on.
#
# Sonnet 5 runs adaptive thinking when `thinking` is absent, so the request
# sets thinking and effort explicitly (#1026). Treat that as a prerequisite of
# any future model bump: without it the output cap silently becomes a shared
# ceiling over thinking plus the JSON answer.
DEFAULT_MODEL="claude-sonnet-5"
# What the request actually uses: config.json's `default_model`/`model` when
# set, else DEFAULT_MODEL. load_runtime_tunables() resolves it, and the same
# value drives pricing, so the request and the cost log cannot name different
# models (#1034).
MODEL="${DEFAULT_MODEL}"
# The answer is one small JSON object, so 2000 tokens is generous. The curl
# timeout is sized to it.
DRAFT_MAX_OUTPUT_TOKENS=2000
CURL_MAX_TIME_SECONDS=120

# ---------------------------------------------------------------------
# Path helpers (env-overridable for tests).
# ---------------------------------------------------------------------

autoheal_dir() {
    printf '%s\n' "${CCGM_AUTOHEAL_DIR:-${HOME}/.claude/autoheal}"
}

config_path() {
    printf '%s\n' "${CCGM_AUTOHEAL_CONFIG:-$(autoheal_dir)/config.json}"
}

last_analyzed_path() {
    printf '%s\n' "$(autoheal_dir)/last-analyzed"
}

cost_log_path() {
    printf '%s\n' "$(autoheal_dir)/cost.log"
}

analyzer_prompt_path() {
    printf '%s\n' "${CCGM_AUTOHEAL_ANALYZER_PROMPT:-${MODULE_ROOT}/lib/analyzer-prompt.md}"
}

logs_dir() {
    printf '%s\n' "${HOME}/.claude/logs"
}

today_str() {
    if [ -n "${CCGM_AUTOHEAL_TODAY:-}" ]; then
        printf '%s\n' "${CCGM_AUTOHEAL_TODAY}"
        return 0
    fi
    python3 -c "import datetime; print(datetime.datetime.now(datetime.timezone.utc).date().isoformat())"
}

# ---------------------------------------------------------------------
# Config-driven tunables (daily_cost_cap_usd, model).
#
# Reads config.json. A missing file, malformed JSON or missing keys fall back
# to defaults. The cap must be positive; anything else is treated as missing.
#
# `model` resolves the same way pricing resolves it (`default_model` then
# `model`, then DEFAULT_MODEL), and the resolved value is what the REQUEST
# uses (#1034).
# ---------------------------------------------------------------------

load_runtime_tunables() {
    local cfg
    cfg="$(config_path)"
    if [ ! -f "${cfg}" ]; then
        return 0
    fi
    local parsed
    parsed=$(
        CONFIG_PATH="${cfg}" \
        DEFAULT_CAP_CENTS="${DAILY_COST_CAP_CENTS_DEFAULT}" \
        DEFAULT_MODEL_ID="${DEFAULT_MODEL}" \
        python3 - <<'PY'
import json
import os

path = os.environ["CONFIG_PATH"]
default_cap_cents = int(os.environ["DEFAULT_CAP_CENTS"])
default_model = os.environ["DEFAULT_MODEL_ID"]

try:
    with open(path, "r", encoding="utf-8") as fh:
        cfg = json.load(fh)
except (OSError, json.JSONDecodeError):
    cfg = {}

if not isinstance(cfg, dict):
    cfg = {}

cap_usd = cfg.get("daily_cost_cap_usd")
if isinstance(cap_usd, (int, float)) and cap_usd > 0:
    cap_cents = int(round(float(cap_usd) * 100))
else:
    cap_cents = default_cap_cents

model = cfg.get("default_model") or cfg.get("model")
if not isinstance(model, str) or not model.strip():
    model = default_model

print(f"{cap_cents}\t{model.strip()}")
PY
    )
    if [ -n "${parsed}" ]; then
        DAILY_COST_CAP_CENTS="$(printf '%s' "${parsed}" | cut -f1)"
        local cfg_model
        cfg_model="$(printf '%s' "${parsed}" | cut -f2)"
        if [ -n "${cfg_model}" ]; then
            MODEL="${cfg_model}"
        fi
    fi
}

# ---------------------------------------------------------------------
# Structured outputs support gate (#1028).
#
# The request sends output_config.format, which only some models accept. A
# model outside this list gets a 400 on every call, so the run stops before
# spending anything and names the model and the fix.
#
# One rule decides membership: the model must BOTH support structured outputs
# AND have a published per-MTok rate, because a model this analyzer can call
# but cannot price would corrupt the cost log the way #1025 did. So the list
# is the published structured-outputs set, minus the two entries with no
# published rate:
#   - claude-opus-4-1: deprecated, retired 2026-08-05, unpriced.
#   - claude-opus-4-5: still active and schema-capable, but no published
#     rate, so spend against it could not be accounted for.
# Every model here has an entry in FALLBACK_PRICING below and in
# autoheal-install.sh's DEFAULT_PRICING, and the pin test fails if that stops
# being true. The remediation message prints this same list, so it can only
# ever recommend a model that is both callable and priced.
#
# Two models are priced but deliberately NOT here: claude-sonnet-4-6 (the
# migration case the installer rewrites) and claude-opus-4-7 (active but not
# on the structured-outputs list). Both keep prices so existing cost.log rows
# and configs still resolve; configuring either one refuses the run rather
# than sending a request the API would reject.
# ---------------------------------------------------------------------

STRUCTURED_OUTPUT_MODELS="claude-fable-5-1 claude-fable-5 claude-mythos-5-1 claude-mythos-5 claude-opus-5 claude-opus-4-8 claude-sonnet-5 claude-haiku-4-5"

supports_structured_outputs() {
    local candidate="$1"
    local known
    for known in ${STRUCTURED_OUTPUT_MODELS}; do
        if [ "${candidate}" = "${known}" ]; then
            return 0
        fi
    done
    return 1
}

# ---------------------------------------------------------------------
# Setup.
# ---------------------------------------------------------------------

mkdir -p "$(autoheal_dir)" "$(logs_dir)"

if ! command -v python3 >/dev/null 2>&1; then
    echo "autoheal-analyze: python3 not found on PATH" >&2
    exit 1
fi

if ! command -v curl >/dev/null 2>&1; then
    echo "autoheal-analyze: curl not found on PATH" >&2
    exit 1
fi

load_runtime_tunables

# The aggregator and draft_proposals.py find the state dir through this.
CCGM_AUTOHEAL_DIR="$(autoheal_dir)"
export CCGM_AUTOHEAL_DIR
CCGM_AUTOHEAL_CONFIG="$(config_path)"
export CCGM_AUTOHEAL_CONFIG

# Originating clone identifier (audit trail).
CLONE_ID="${CCGM_AUTOHEAL_CLONE_ID:-$(basename "${PWD}")}"

TODAY_ISO="$(today_str)"
DATE="${DATE_ARG:-${TODAY_ISO}}"

TMP_DIR="$(mktemp -d -t autoheal_analyze.XXXXXX)"
trap 'rm -rf "${TMP_DIR}"' EXIT

# ---------------------------------------------------------------------
# Per-run bookkeeping, written to runs/{today}.json so autoheal-digest.sh
# can render it: a call that was refused, stopped at the cap or came back
# empty is otherwise only a stderr line in a launchd log nobody reads.
# ---------------------------------------------------------------------

RUN_TRUNCATED_CALLS=0
RUN_FAILED_CALLS=0
RUN_FAILURES=""
RUN_DROPS=""
RUN_SELECTED=0
RUN_DRAFTED=0
RUN_SKIPPED=0
RUN_ISSUES=0

write_run_summary() {
    local runs_dir
    runs_dir="$(autoheal_dir)/runs"
    mkdir -p "${runs_dir}"
    RUN_DAY="${DATE}" \
    RUN_TRUNCATED_CALLS="${RUN_TRUNCATED_CALLS}" \
    RUN_FAILED_CALLS="${RUN_FAILED_CALLS}" \
    RUN_FAILURES="${RUN_FAILURES}" \
    RUN_DROPS="${RUN_DROPS}" \
    RUN_SELECTED="${RUN_SELECTED}" \
    RUN_DRAFTED="${RUN_DRAFTED}" \
    RUN_SKIPPED="${RUN_SKIPPED}" \
    RUN_ISSUES="${RUN_ISSUES}" \
    RUN_MODEL="${MODEL}" \
    RUN_PATH="${runs_dir}/${TODAY_ISO}.json" \
    python3 - <<'PY'
import datetime as dt
import json
import os

failures = []
for line in (os.environ.get("RUN_FAILURES") or "").splitlines():
    line = line.strip()
    if not line:
        continue
    day, _, reason = line.partition(" ")
    failures.append({"day": day, "reason": reason or "unknown"})

dropped = {}
for line in (os.environ.get("RUN_DROPS") or "").splitlines():
    line = line.strip()
    if line:
        dropped[line] = dropped.get(line, 0) + 1

summary = {
    "date": os.environ["RUN_DAY"],
    "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
    "model": os.environ.get("RUN_MODEL", ""),
    "signatures_selected": int(os.environ.get("RUN_SELECTED") or 0),
    "drafted": int(os.environ.get("RUN_DRAFTED") or 0),
    "skipped": int(os.environ.get("RUN_SKIPPED") or 0),
    "issues": int(os.environ.get("RUN_ISSUES") or 0),
    "dropped": dropped,
    "truncated_calls": int(os.environ.get("RUN_TRUNCATED_CALLS") or 0),
    "failed_calls": int(os.environ.get("RUN_FAILED_CALLS") or 0),
    "failures": failures,
}

path = os.environ["RUN_PATH"]
tmp = path + ".tmp"
with open(tmp, "w", encoding="utf-8") as fh:
    json.dump(summary, fh, indent=2)
    fh.write("\n")
os.replace(tmp, path)
PY
}

# `last-analyzed` is the date of the last run that finished, kept so
# /autoheal can show it. It gates nothing: the aggregator's rolling window
# and its coverage check decide what is drafted.
mark_run_complete() {
    printf '%s\n' "${TODAY_ISO}" > "$(last_analyzed_path)"
}

# ---------------------------------------------------------------------
# Step 1: aggregate (deterministic, no model call).
# ---------------------------------------------------------------------

if ! python3 "${SCRIPT_DIR}/autoheal-aggregate.py" --date "${DATE}" >&2; then
    echo "autoheal-analyze: aggregation failed for ${DATE}" >&2
    exit 1
fi

# ---------------------------------------------------------------------
# Step 2: plan. Routes up to 3 qualifying signatures and builds requests.
# ---------------------------------------------------------------------

python3 "${MODULE_ROOT}/lib/draft_proposals.py" plan \
    --date "${DATE}" \
    --out "${TMP_DIR}" \
    --model "${MODEL}" \
    --max-tokens "${DRAFT_MAX_OUTPUT_TOKENS}" \
    --prompt "$(analyzer_prompt_path)" \
    --schema "${MODULE_ROOT}/lib/proposal-schema.json" \
    --map "${MODULE_ROOT}/lib/signature-module-map.json" \
    --config "$(config_path)" \
    --clone-id "${CLONE_ID}" >&2
PLAN_RC=$?
if [ "${PLAN_RC}" -ne 0 ]; then
    echo "autoheal-analyze: drafting plan failed for ${DATE} (rc=${PLAN_RC})" >&2
    exit 1
fi

ITEMS=""
while IFS=$'\t' read -r tag a b; do
    case "${tag}" in
        selected)
            RUN_SELECTED="${a}"
            ;;
        issue)
            RUN_ISSUES=$((RUN_ISSUES + 1))
            echo "autoheal-analyze: ${a}: hook denial in ${b}; issue proposal drafted locally, no model call" >&2
            ;;
        note)
            echo "autoheal-analyze: ${a}: drafting skipped (${b})" >&2
            ;;
        item)
            ITEMS="${ITEMS}${a} ${b}
"
            ;;
    esac
done < "${TMP_DIR}/plan.tsv"

if [ "${RUN_SELECTED}" -eq 0 ]; then
    echo "autoheal-analyze: no qualifying signatures for ${DATE}; no API call." >&2
    write_run_summary
    mark_run_complete
    exit 0
fi

if [ -z "${ITEMS}" ]; then
    echo "autoheal-analyze: nothing to send to the model for ${DATE} (${RUN_ISSUES} issue proposal(s) drafted)." >&2
    write_run_summary
    mark_run_complete
    exit 0
fi

# ---------------------------------------------------------------------
# Guards that stop a paid call before it is made.
# ---------------------------------------------------------------------

# The request carries output_config.format, so a model that cannot honor it
# would 400 on every call. Stop before spending anything.
if ! supports_structured_outputs "${MODEL}"; then
    echo "autoheal-analyze: configured model '${MODEL}' does not support structured outputs" >&2
    echo "autoheal-analyze: the analyzer sends output_config.format, which this model would reject." >&2
    echo "autoheal-analyze: set default_model in $(config_path) to one of: ${STRUCTURED_OUTPUT_MODELS}" >&2
    echo "autoheal-analyze: no call was made." >&2
    exit 2
fi

if [ -z "${ANTHROPIC_API_KEY:-}" ]; then
    echo "autoheal-analyze: ANTHROPIC_API_KEY not set; skipping model calls (local-only deployment is fine)." >&2
    exit 0
fi

today_cost_cents() {
    COST_LOG="$(cost_log_path)" TODAY_ISO="${TODAY_ISO}" python3 - <<'PY'
import os

path = os.environ["COST_LOG"]
today = os.environ["TODAY_ISO"]

total = 0.0
if os.path.isfile(path):
    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            parts = line.split("\t")
            if len(parts) >= 4 and parts[0] == today:
                try:
                    total += float(parts[3])
                except ValueError:
                    pass

print(int(round(total * 100)))
PY
}

CURRENT_COST_CENTS="$(today_cost_cents)"
if [ "${CURRENT_COST_CENTS}" -ge "${DAILY_COST_CAP_CENTS}" ]; then
    echo "autoheal-analyze: daily cost cap reached (${CURRENT_COST_CENTS}c >= ${DAILY_COST_CAP_CENTS}c); skipping." >&2
    exit 2
fi

# ---------------------------------------------------------------------
# API plumbing.
# ---------------------------------------------------------------------

sandbox_prefix() {
    if [ "${USE_ANALYZER_SANDBOX:-0}" = "1" ] && command -v sandbox-exec >/dev/null 2>&1; then
        printf 'sandbox-exec -f %s ' "${MODULE_ROOT}/lib/analyzer-sandbox.sb"
    fi
}

redacted_body_excerpt() {
    # Print a short, secret-scrubbed excerpt of an error body. Reuses
    # hook_utils.redact_secrets when it is importable, and falls back to a
    # conservative key-shape scrub so a body is never echoed raw.
    local body_file="$1"
    BODY_FILE="${body_file}" HOOK_LIB="${MODULE_ROOT}/../hooks/lib" python3 - <<'PY'
import os
import re
import sys

path = os.environ["BODY_FILE"]
try:
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        body = fh.read(4000)
except OSError:
    print("  (no response body captured)")
    sys.exit(0)

try:
    sys.path.insert(0, os.environ["HOOK_LIB"])
    from hook_utils import redact_secrets  # noqa: E402
    body = redact_secrets(body)
except Exception:
    body = re.sub(r"sk-[A-Za-z0-9_\-]{16,}", "[redacted]", body)
    body = re.sub(r"(?i)(api[_-]?key\"?\s*[:=]\s*\"?)[^\"\s,}]+", r"\1[redacted]", body)

body = " ".join(body.split())
if len(body) > 400:
    body = body[:400] + " ..."
print(f"  body: {body}" if body else "  (empty response body)")
PY
}

api_post() {
    # api_post <url> <request body file> <response file>
    # Prints the HTTP status code (curl -w) on stdout, like the old call did.
    # -w with -o keeps the body in the file: without it a 4xx error body was
    # parsed as if it were a successful response.
    local url="$1" body="$2" out="$3" sb
    sb="$(sandbox_prefix)"
    # shellcheck disable=SC2086
    ${sb}curl -s -S \
        -H "x-api-key: ${ANTHROPIC_API_KEY}" \
        -H "anthropic-version: 2023-06-01" \
        -H "content-type: application/json" \
        --max-time "${CURL_MAX_TIME_SECONDS}" \
        -o "${out}" \
        -w '%{http_code}' \
        "${url}" \
        --data-binary @"${body}"
}

API_URL="${CCGM_AUTOHEAL_API_URL:-https://api.anthropic.com/v1/messages}"
COUNT_URL="${API_URL}/count_tokens"

fail_item() {
    # fail_item <signature id> <reason>: count it, say it, move on. A failed
    # call is not retried and not held.
    RUN_FAILED_CALLS=$((RUN_FAILED_CALLS + 1))
    RUN_FAILURES="${RUN_FAILURES}${DATE} ${1}: ${2}
"
    echo "autoheal-analyze: ${1} failed (${2}); not retried." >&2
}

# ---------------------------------------------------------------------
# Parse a Messages response: cost accounting, stop_reason checks, answer text.
# Exit 4 means the call happened and was billed but produced nothing usable.
# ---------------------------------------------------------------------

parse_response() {
    # parse_response <response file> <answer out file> <marker dir>
    python3 - \
            "$1" \
            "$2" \
            "$3" \
            "$(cost_log_path)" \
            "${TODAY_ISO}" \
            "$(config_path)" \
            "${MODEL}" \
        <<'PY'
import json
import os
import sys

response_path, answer_path, marker_dir, cost_log_path, today_iso, config_path, request_model = sys.argv[1:8]

# Exit code for "the call happened but produced nothing usable".
EXIT_UNUSABLE_RESPONSE = 4


def append_locked(path, data):
    """Locked append, same shape as hook_utils.file_locked_append, inlined so
    this script does not import the hook lib. fcntl.flock(LOCK_EX) on the open
    descriptor serializes appends from sibling clones."""
    import fcntl

    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    payload = data if data.endswith("\n") else data + "\n"
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        try:
            os.write(fd, payload.encode("utf-8"))
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)


def append_cost(path, today, input_tokens, output_tokens, cost_usd, model):
    # `model` is appended as a 5th tab-separated field. Older cost.log lines
    # lacking this field still parse (today_cost_cents only reads parts[0..3]);
    # see issue #497. input_tokens counts cached tokens too.
    line = f"{today}\t{input_tokens}\t{output_tokens}\t{cost_usd:.6f}\t{model}"
    append_locked(path, line)


# Per-model pricing (USD per million tokens), from the Anthropic Current
# Models table, checked 2026-09-02. Matches autoheal-install.sh defaults; the
# install step is the source of truth, this dict only fires when the config
# file is unreadable or its cost_pricing block is missing entirely.
#
# Every model in STRUCTURED_OUTPUT_MODELS appears here, so a config the gate
# accepts can always be priced. Mythos 5/5.1 are priced at the Fable rate on
# the published statement that they are the same tier at the same per-token
# price. The last two entries are priced but NOT gated: an install may still
# hold a claude-sonnet-4-6 pin (the installer migrates it) and older cost.log
# rows may name claude-opus-4-7, which carried the retired Opus 4.1 rate
# ($15/$75) until the #1033 review -- Opus 4.7 and 4.8 are both $5/$25.
FALLBACK_PRICING = {
    "claude-fable-5-1": {"input_per_million": 10.0, "output_per_million": 50.0},
    "claude-fable-5": {"input_per_million": 10.0, "output_per_million": 50.0},
    "claude-mythos-5-1": {"input_per_million": 10.0, "output_per_million": 50.0},
    "claude-mythos-5": {"input_per_million": 10.0, "output_per_million": 50.0},
    "claude-opus-5": {"input_per_million": 5.0, "output_per_million": 25.0},
    "claude-opus-4-8": {"input_per_million": 5.0, "output_per_million": 25.0},
    "claude-sonnet-5": {"input_per_million": 2.0, "output_per_million": 10.0},
    "claude-haiku-4-5": {"input_per_million": 1.0, "output_per_million": 5.0},
    "claude-sonnet-4-6": {"input_per_million": 3.0, "output_per_million": 15.0},
    "claude-opus-4-7": {"input_per_million": 5.0, "output_per_million": 25.0},
}
# The last-resort rate for a model nothing prices. It tracks the model this
# script actually calls, so the guess is at least the right order of magnitude
# for the traffic that generated it.
SONNET_FALLBACK_MODEL = "claude-sonnet-5"
SONNET_FALLBACK = FALLBACK_PRICING[SONNET_FALLBACK_MODEL]

# Prompt caching multipliers on the input rate: a 5-minute cache write bills at
# 1.25x, a cache read at 0.1x.
CACHE_WRITE_MULTIPLIER = 1.25
CACHE_READ_MULTIPLIER = 0.1


def load_cfg(path):
    try:
        with open(path, "r", encoding="utf-8") as fh:
            cfg = json.load(fh)
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(cfg, dict):
        return {}
    return cfg


def resolve_pricing(cfg, model):
    """Return (model_id, pricing_dict) for the model the request used.

    `model` is passed in rather than re-derived from config here: the request
    and the price must key off one value, or the cost log ends up naming a
    model that was never called (#1034)."""
    pricing_map = cfg.get("cost_pricing")
    if not isinstance(pricing_map, dict):
        pricing_map = FALLBACK_PRICING
    pricing = pricing_map.get(model)
    if not isinstance(pricing, dict) or "input_per_million" not in pricing or "output_per_million" not in pricing:
        sys.stderr.write(
            f"WARNING: no cost_pricing for model {model}; "
            f"falling back to {SONNET_FALLBACK_MODEL} pricing\n"
        )
        pricing = SONNET_FALLBACK
    return model, pricing


def mark(name, contents=""):
    """Leave a marker the shell reads before deleting the temp dir."""
    try:
        with open(os.path.join(marker_dir, name), "w", encoding="utf-8") as fh:
            fh.write(contents)
    except OSError:
        pass


try:
    with open(response_path, "r", encoding="utf-8") as fh:
        response = json.load(fh)
except (OSError, json.JSONDecodeError) as exc:
    print(f"FATAL: cannot read response {response_path}: {exc}", file=sys.stderr)
    mark("CALL_FAILED", "unreadable_response")
    sys.exit(EXIT_UNUSABLE_RESPONSE)

# Cost accounting (best-effort; a response may omit usage).
usage = response.get("usage") if isinstance(response, dict) else None
if isinstance(usage, dict):
    in_tok = int(usage.get("input_tokens", 0) or 0)
    out_tok = int(usage.get("output_tokens", 0) or 0)
    cache_write = int(usage.get("cache_creation_input_tokens", 0) or 0)
    cache_read = int(usage.get("cache_read_input_tokens", 0) or 0)
else:
    in_tok = out_tok = cache_write = cache_read = 0

cfg = load_cfg(config_path)
model_id, pricing = resolve_pricing(cfg, request_model)
in_rate = float(pricing["input_per_million"])
cost = (
    in_tok * in_rate
    + cache_write * in_rate * CACHE_WRITE_MULTIPLIER
    + cache_read * in_rate * CACHE_READ_MULTIPLIER
    + out_tok * float(pricing["output_per_million"])
) / 1_000_000.0
append_cost(cost_log_path, today_iso, in_tok + cache_write + cache_read, out_tok, cost, model_id)

# A call that did not end cleanly produced no usable answer, whatever it cost.
# `max_tokens` means the answer was cut off; `refusal` means the model
# declined -- plausible here, since every input is security-shaped tool output.
stop_reason = response.get("stop_reason") if isinstance(response, dict) else None
if stop_reason == "max_tokens":
    print(
        "WARN: analyzer response stopped at the output cap (stop_reason=max_tokens); "
        "treating it as a failed call, not a short answer",
        file=sys.stderr,
    )
    mark("TRUNCATED")
    mark("CALL_FAILED", "stop_reason_max_tokens")
    sys.exit(EXIT_UNUSABLE_RESPONSE)

if stop_reason is not None and stop_reason != "end_turn":
    print(
        f"WARN: analyzer response ended with stop_reason={stop_reason}; treating it as a failed call",
        file=sys.stderr,
    )
    mark("CALL_FAILED", f"stop_reason_{stop_reason}")
    sys.exit(EXIT_UNUSABLE_RESPONSE)

parts = []
content = response.get("content") if isinstance(response, dict) else None
for block in content if isinstance(content, list) else []:
    if isinstance(block, dict) and block.get("type") == "text" and isinstance(block.get("text"), str):
        parts.append(block["text"])
text = "".join(parts)
if not text.strip():
    # An error body, an empty content array, or blocks that are not type
    # "text": a failed call, not a clean zero-proposal answer.
    print("WARN: analyzer response carried no assistant text; treating it as a failed call", file=sys.stderr)
    mark("CALL_FAILED", "empty_response_text")
    sys.exit(EXIT_UNUSABLE_RESPONSE)

with open(answer_path, "w", encoding="utf-8") as fh:
    fh.write(text)
PY
}

# ---------------------------------------------------------------------
# Step 3: one signature at a time. Measure, send, parse, check, write.
# ---------------------------------------------------------------------

process_item() {
    local idx="$1" sid="$2"
    local stem="${TMP_DIR}/item-${idx}"
    local http_code="" curl_rc=0

    # Measure the real input. count_tokens is free; a request over the limit
    # is never sent.
    http_code="$(api_post "${COUNT_URL}" "${stem}.count.json" "${stem}.count-response.json")" || curl_rc=$?
    if [ "${curl_rc}" -ne 0 ]; then
        fail_item "${sid}" "count_tokens_transport_exit_${curl_rc}"
        return 1
    fi
    if [ "${http_code}" != "200" ]; then
        redacted_body_excerpt "${stem}.count-response.json" >&2
        fail_item "${sid}" "count_tokens_http_${http_code}"
        return 1
    fi
    local tokens
    tokens="$(python3 -c "
import json, sys
try:
    n = json.load(open(sys.argv[1]))['input_tokens']
    print(n if isinstance(n, int) and n >= 0 else '')
except Exception:
    print('')
" "${stem}.count-response.json")"
    if [ -z "${tokens}" ]; then
        fail_item "${sid}" "count_tokens_bad_response"
        return 1
    fi
    echo "autoheal-analyze: ${sid}: input ${tokens} tokens (limit ${INPUT_TOKEN_LIMIT})" >&2
    if [ "${tokens}" -gt "${INPUT_TOKEN_LIMIT}" ]; then
        fail_item "${sid}" "input_over_limit ${tokens} > ${INPUT_TOKEN_LIMIT}"
        return 1
    fi

    curl_rc=0
    http_code="$(api_post "${API_URL}" "${stem}.request.json" "${stem}.response.json")" || curl_rc=$?
    if [ "${curl_rc}" -ne 0 ]; then
        fail_item "${sid}" "transport_exit_${curl_rc}"
        return 1
    fi
    if [ "${http_code}" != "200" ]; then
        redacted_body_excerpt "${stem}.response.json" >&2
        fail_item "${sid}" "http_${http_code}"
        return 1
    fi

    local pr_rc=0
    parse_response "${stem}.response.json" "${stem}.answer.txt" "${TMP_DIR}" || pr_rc=$?
    if [ -f "${TMP_DIR}/TRUNCATED" ]; then
        RUN_TRUNCATED_CALLS=$((RUN_TRUNCATED_CALLS + 1))
        rm -f "${TMP_DIR}/TRUNCATED"
    fi
    if [ "${pr_rc}" -ne 0 ]; then
        local why="parse_rc_${pr_rc}"
        if [ -f "${TMP_DIR}/CALL_FAILED" ]; then
            why="$(tr -d '\n' < "${TMP_DIR}/CALL_FAILED" || true)"
            rm -f "${TMP_DIR}/CALL_FAILED"
        fi
        fail_item "${sid}" "${why}"
        return 1
    fi

    local result
    result="$(python3 "${MODULE_ROOT}/lib/draft_proposals.py" finish \
        --meta "${stem}.json" \
        --answer "${stem}.answer.txt" \
        --date "${DATE}" \
        --rejected-log "$(logs_dir)/autoheal-rejected-${TODAY_ISO}.log" \
        --clone-id "${CLONE_ID}")" || {
        fail_item "${sid}" "finish_failed"
        return 1
    }
    local outcome reason
    outcome="$(printf '%s' "${result}" | python3 -c "import json,sys; print(json.load(sys.stdin)['outcome'])")"
    reason="$(printf '%s' "${result}" | python3 -c "import json,sys; print(json.load(sys.stdin)['reason'])")"
    case "${outcome}" in
        rule_insert)
            RUN_DRAFTED=$((RUN_DRAFTED + 1))
            echo "autoheal-analyze: ${sid}: rule_insert proposal written." >&2
            ;;
        skip)
            RUN_SKIPPED=$((RUN_SKIPPED + 1))
            echo "autoheal-analyze: ${sid}: model skipped; recorded so it is not sent again." >&2
            ;;
        *)
            RUN_DROPS="${RUN_DROPS}${reason}
"
            echo "autoheal-analyze: ${sid}: answer dropped (${reason})." >&2
            ;;
    esac
    return 0
}

OVERALL_RC=0
while read -r idx sid; do
    [ -z "${idx}" ] && continue
    if ! process_item "${idx}" "${sid}"; then
        OVERALL_RC=1
    fi
done <<< "${ITEMS}"

write_run_summary
if [ "${OVERALL_RC}" -eq 0 ]; then
    mark_run_complete
fi

exit "${OVERALL_RC}"
