#!/usr/bin/env bash
# CCGM autoheal — daily analyzer (Epic 6).
#
# Reads recent autoheal events, pre-extracts transcript excerpts in a
# pure-Python phase (NOT inside the API call so the raw transcript tree
# never crosses the API boundary), calls the Anthropic Messages API
# directly via curl, validates the proposals against the locked schema,
# applies the privilege-escalation gate, and appends accepted proposals
# to ~/.claude/autoheal/proposals/{date}.jsonl via the cross-clone
# file lock.
#
# Why curl and not `claude -p`: no nested-tool runtime means no
# process-exec attack surface, and the analyzer's contract is a pure
# prompt -> JSON pipeline. See plan.md §3.13 and §5 Epic 6.
#
# Env vars:
#   ANTHROPIC_API_KEY            REQUIRED unless --dry-run or fixture mode.
#                                 Read from the shell env at run time.
#                                 NEVER baked into the launchd plist.
#   CCGM_AUTOHEAL_DIR            Root of autoheal state (default
#                                 ~/.claude/autoheal). Tests override.
#   CCGM_AUTOHEAL_EVENTS_DIR     Events dir (default $CCGM_AUTOHEAL_DIR/events).
#   CCGM_AUTOHEAL_PROPOSALS_DIR  Proposals dir (default
#                                 $CCGM_AUTOHEAL_DIR/proposals).
#   CCGM_AUTOHEAL_CONFIG         Config JSON path (default
#                                 $CCGM_AUTOHEAL_DIR/config.json).
#   CCGM_AUTOHEAL_ANALYZER_PROMPT Override path for the analyzer prompt
#                                 (default <module>/lib/analyzer-prompt.md).
#   CCGM_AUTOHEAL_API_URL        Override API endpoint for fixture tests
#                                 (default https://api.anthropic.com/v1/messages).
#   CCGM_AUTOHEAL_FIXTURE_API_RESPONSE
#                                 When set to a file path, the script
#                                 reads that file as the API response
#                                 instead of calling curl. Tests only.
#   CCGM_AUTOHEAL_PROMPT_LOG     If set, the constructed prompt is
#                                 written here for inspection. Tests
#                                 only.
#   CCGM_AUTOHEAL_TODAY          YYYY-MM-DD override.
#   CCGM_AUTOHEAL_CLONE_ID       Originating clone label (default cwd basename).
#   USE_ANALYZER_SANDBOX         If 1 and sandbox-exec exists, wraps the
#                                 curl call in the seatbelt profile.
#
# Exit codes:
#   0  success (including "nothing to do" cases)
#   1  fatal config/setup error
#   2  daily cost cap reached; skipped without error
#
# This script is invoked by `autoheal-daily.sh` (Epic 7) but is also
# runnable standalone for development and testing.

set -u
set -o pipefail

# ---------------------------------------------------------------------
# Resolve module paths.
# ---------------------------------------------------------------------

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MODULE_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

# ---------------------------------------------------------------------
# Tunables (overridable via config; defaults match plan.md §3.7).
# ---------------------------------------------------------------------

MAX_INPUT_TOKENS=40000              # Hard input cap (rough char/4 estimate).
DAILY_COST_CAP_CENTS=50             # $0.50/day in cents.
DEFAULT_MODEL="claude-sonnet-4-6"   # Configurable in config.json.
DEFAULT_MAX_OUTPUT_TOKENS=4096
LOOKBACK_DAYS=7                     # Walk back at most this many days.
CALIBRATION_WINDOW_DAYS=7

# ---------------------------------------------------------------------
# Path helpers (env-overridable for tests).
# ---------------------------------------------------------------------

autoheal_dir() {
    printf '%s\n' "${CCGM_AUTOHEAL_DIR:-${HOME}/.claude/autoheal}"
}

events_dir() {
    printf '%s\n' "${CCGM_AUTOHEAL_EVENTS_DIR:-$(autoheal_dir)/events}"
}

proposals_dir() {
    printf '%s\n' "${CCGM_AUTOHEAL_PROPOSALS_DIR:-$(autoheal_dir)/proposals}"
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

proposal_schema_path() {
    printf '%s\n' "${MODULE_ROOT}/lib/proposal-schema.json"
}

today_str() {
    if [ -n "${CCGM_AUTOHEAL_TODAY:-}" ]; then
        printf '%s\n' "${CCGM_AUTOHEAL_TODAY}"
        return 0
    fi
    python3 -c "import datetime; print(datetime.datetime.now(datetime.timezone.utc).date().isoformat())"
}

logs_dir() {
    printf '%s\n' "${HOME}/.claude/logs"
}

# ---------------------------------------------------------------------
# Setup: ensure dirs and dependencies exist.
# ---------------------------------------------------------------------

mkdir -p "$(autoheal_dir)" "$(events_dir)" "$(proposals_dir)" "$(logs_dir)"

if ! command -v python3 >/dev/null 2>&1; then
    echo "autoheal-analyze: python3 not found on PATH" >&2
    exit 1
fi

if ! command -v curl >/dev/null 2>&1; then
    echo "autoheal-analyze: curl not found on PATH" >&2
    exit 1
fi

# ---------------------------------------------------------------------
# API-key + fixture handling.
# ---------------------------------------------------------------------

FIXTURE_RESPONSE="${CCGM_AUTOHEAL_FIXTURE_API_RESPONSE:-}"
if [ -z "${FIXTURE_RESPONSE}" ] && [ -z "${ANTHROPIC_API_KEY:-}" ]; then
    echo "autoheal-analyze: ANTHROPIC_API_KEY not set; skipping (local-only deployment is fine)." >&2
    exit 0
fi

# Originating clone identifier (audit trail; cross-clone dedup).
CLONE_ID="${CCGM_AUTOHEAL_CLONE_ID:-$(basename "${PWD}")}"

# ---------------------------------------------------------------------
# Compute the list of unanalyzed days.
# ---------------------------------------------------------------------

compute_days() {
    python3 - <<'PY'
import datetime as dt
import os

last_path = os.environ["LAST_PATH"]
lookback = int(os.environ["LOOKBACK_DAYS"])
today_iso = os.environ["TODAY_ISO"]
events_dir = os.environ["EVENTS_DIR"]

today = dt.date.fromisoformat(today_iso)

last = None
if os.path.isfile(last_path):
    try:
        with open(last_path, "r", encoding="utf-8") as fh:
            txt = fh.read().strip()
            if txt:
                last = dt.date.fromisoformat(txt)
    except (OSError, ValueError):
        last = None

# Window: from (last + 1) up to today; bounded by LOOKBACK_DAYS.
start = today - dt.timedelta(days=lookback)
if last is not None:
    start = max(start, last + dt.timedelta(days=1))

days = []
cursor = start
while cursor <= today:
    iso = cursor.isoformat()
    if os.path.isfile(os.path.join(events_dir, iso + ".jsonl")):
        days.append(iso)
    cursor += dt.timedelta(days=1)

print("\n".join(days))
PY
}

TODAY_ISO="$(today_str)"

export LAST_PATH="$(last_analyzed_path)"
export LOOKBACK_DAYS
export TODAY_ISO
export EVENTS_DIR="$(events_dir)"
DAYS_TO_ANALYZE="$(compute_days)"

if [ -z "${DAYS_TO_ANALYZE}" ]; then
    echo "autoheal-analyze: no unanalyzed event days in the last ${LOOKBACK_DAYS} days." >&2
    # Still bump last-analyzed so we don't keep re-scanning empty space.
    printf '%s\n' "${TODAY_ISO}" > "$(last_analyzed_path)"
    exit 0
fi

# ---------------------------------------------------------------------
# Calibration window: are we within the first 7 active days?
# ---------------------------------------------------------------------

calibration_mode() {
    python3 - <<'PY'
import datetime as dt
import os

last_path = os.environ["LAST_PATH"]
window = int(os.environ["CALIBRATION_WINDOW_DAYS"])

if not os.path.isfile(last_path):
    print("true")
    raise SystemExit(0)

# We approximate days-since-first-analysis by reading the file's mtime
# vs now. A more precise version would track a "first-analyzed" date,
# but mtime is cheap and bounded; if the user resets state, the
# calibration window resets too.
import time

age_days = (time.time() - os.path.getmtime(last_path)) / 86400.0

# When the existing `last-analyzed` is within the calibration window
# (i.e. the file is recent), we are still in calibration. Conservative
# default when uncertain: assume calibration.
print("true" if age_days < window else "false")
PY
}

export LAST_PATH="$(last_analyzed_path)"
export CALIBRATION_WINDOW_DAYS
CALIBRATION_MODE="$(calibration_mode)"

# ---------------------------------------------------------------------
# Daily cost cap. Skip whole script if today's spend already hit.
# ---------------------------------------------------------------------

today_cost_cents() {
    python3 - <<'PY'
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

export COST_LOG="$(cost_log_path)"
export TODAY_ISO
CURRENT_COST_CENTS="$(today_cost_cents)"

if [ "${CURRENT_COST_CENTS}" -ge "${DAILY_COST_CAP_CENTS}" ]; then
    echo "autoheal-analyze: daily cost cap reached (${CURRENT_COST_CENTS}c >= ${DAILY_COST_CAP_CENTS}c); skipping." >&2
    exit 2
fi

# ---------------------------------------------------------------------
# Optional sandbox wrapper.
# ---------------------------------------------------------------------

sandbox_prefix() {
    if [ "${USE_ANALYZER_SANDBOX:-0}" = "1" ] && command -v sandbox-exec >/dev/null 2>&1; then
        printf 'sandbox-exec -f %s ' "${MODULE_ROOT}/lib/analyzer-sandbox.sb"
    fi
}

# ---------------------------------------------------------------------
# Per-day processing.
# ---------------------------------------------------------------------

analyze_one_day() {
    local day_iso="$1"

    local events_file="$(events_dir)/${day_iso}.jsonl"
    if [ ! -f "${events_file}" ]; then
        return 0
    fi

    # Pre-extract transcript excerpts AND build the API request payload
    # in one Python pass. We keep the whole pre-processing phase outside
    # the sandbox so the broader transcript tree is not exposed across
    # the API boundary.
    local tmp_dir
    tmp_dir="$(mktemp -d -t autoheal_analyze.XXXXXX)"

    # Run the pre-extract; capture its exit code without `!` so we can
    # distinguish "rejected for size" (rc=3) from "fatal error" (rc!=0,3).
    set +e
    python3 - \
            "${day_iso}" \
            "${events_file}" \
            "${tmp_dir}" \
            "${MAX_INPUT_TOKENS}" \
            "$(analyzer_prompt_path)" \
            "${CLONE_ID}" \
            "${CALIBRATION_MODE}" \
            "${DEFAULT_MODEL}" \
            "${DEFAULT_MAX_OUTPUT_TOKENS}" \
            <<'PY'
import datetime as dt
import json
import os
import sys

day_iso = sys.argv[1]
events_file = sys.argv[2]
tmp_dir = sys.argv[3]
max_input_tokens = int(sys.argv[4])
prompt_path = sys.argv[5]
clone_id = sys.argv[6]
calibration_mode = sys.argv[7] == "true"
model = sys.argv[8]
max_output_tokens = int(sys.argv[9])


def load_events(path):
    out = []
    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(rec, dict):
                out.append(rec)
    return out


def excerpt_transcript(transcript_path, around_ts, window=3):
    """Return up to `window` turns before and after `around_ts` from
    the user's session JSONL. Returns [] when the file is unreadable
    or the field is missing (the current event schema does not include
    `transcript_path`; this is forward-compatible scaffolding)."""
    if not transcript_path:
        return []
    if not isinstance(transcript_path, str):
        return []
    if not os.path.isfile(transcript_path):
        return []
    turns = []
    try:
        with open(transcript_path, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                turns.append(rec)
    except OSError:
        return []

    if not turns:
        return []

    # Best-effort index: find the first turn whose timestamp is >=
    # around_ts. If timestamps are missing, fall back to the middle.
    idx = len(turns) // 2
    if around_ts:
        for i, t in enumerate(turns):
            ts = t.get("timestamp") or t.get("ts") or ""
            if ts and ts >= around_ts:
                idx = i
                break

    lo = max(0, idx - window)
    hi = min(len(turns), idx + window + 1)
    return turns[lo:hi]


events = load_events(events_file)

# Build per-event excerpt list (best-effort; tolerates missing schema
# field — schema is owned by Epic 3 and may grow later).
event_records = []
for ev in events:
    excerpts = excerpt_transcript(
        ev.get("transcript_path"),
        ev.get("timestamp") or ev.get("ts") or "",
    )
    event_records.append({
        "event": ev,
        "excerpts": excerpts,
    })

# Read the analyzer prompt.
try:
    with open(prompt_path, "r", encoding="utf-8") as fh:
        analyzer_prompt = fh.read()
except OSError as exc:
    print(f"FATAL: cannot read analyzer prompt at {prompt_path}: {exc}", file=sys.stderr)
    sys.exit(1)

# Compose the messages payload.
runtime_context = {
    "date": day_iso,
    "originating_clone": clone_id,
    "calibration_mode": calibration_mode,
    "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
}

user_payload = {
    "runtime_context": runtime_context,
    "events": event_records,
}

# Token estimate: rough char/4 over (prompt + serialized payload).
serialized = json.dumps(user_payload, ensure_ascii=False)
char_total = len(analyzer_prompt) + len(serialized)
est_tokens = char_total // 4

if est_tokens > max_input_tokens:
    print(
        f"WARN: estimated input tokens ({est_tokens}) > cap ({max_input_tokens}); rejecting day {day_iso}",
        file=sys.stderr,
    )
    # Write a marker so the caller knows we rejected for size.
    with open(os.path.join(tmp_dir, "REJECT_TOKEN_CAP"), "w", encoding="utf-8") as fh:
        fh.write(f"{est_tokens}\n")
    sys.exit(3)

# Build the API request body.
request_body = {
    "model": model,
    "max_tokens": max_output_tokens,
    "system": analyzer_prompt,
    "messages": [
        {
            "role": "user",
            "content": serialized,
        }
    ],
}

with open(os.path.join(tmp_dir, "request.json"), "w", encoding="utf-8") as fh:
    json.dump(request_body, fh)

# Also write the human-readable prompt log if requested.
prompt_log = os.environ.get("CCGM_AUTOHEAL_PROMPT_LOG")
if prompt_log:
    parent = os.path.dirname(prompt_log)
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(prompt_log, "w", encoding="utf-8") as fh:
        fh.write("SYSTEM:\n")
        fh.write(analyzer_prompt)
        fh.write("\n\nUSER:\n")
        fh.write(serialized)
        fh.write("\n")

print("OK")
PY
    local pe_rc=$?
    set -e

    if [ "${pe_rc}" -eq 3 ]; then
        # Token cap rejected this day; continue with other days.
        rm -rf "${tmp_dir}"
        return 0
    fi
    if [ "${pe_rc}" -ne 0 ]; then
        echo "autoheal-analyze: Python pre-extract failed for ${day_iso} (rc=${pe_rc})" >&2
        rm -rf "${tmp_dir}"
        return 1
    fi

    local request_file="${tmp_dir}/request.json"

    # ---------------------------------------------------------------
    # API call (or fixture replay for tests).
    # ---------------------------------------------------------------

    local response_file="${tmp_dir}/response.json"

    if [ -n "${FIXTURE_RESPONSE}" ]; then
        if [ ! -f "${FIXTURE_RESPONSE}" ]; then
            echo "autoheal-analyze: fixture file not found: ${FIXTURE_RESPONSE}" >&2
            rm -rf "${tmp_dir}"
            return 1
        fi
        cp "${FIXTURE_RESPONSE}" "${response_file}"
    else
        local api_url="${CCGM_AUTOHEAL_API_URL:-https://api.anthropic.com/v1/messages}"
        local sb
        sb="$(sandbox_prefix)"
        # shellcheck disable=SC2086
        if ! ${sb}curl -s -S \
                -H "x-api-key: ${ANTHROPIC_API_KEY}" \
                -H "anthropic-version: 2023-06-01" \
                -H "content-type: application/json" \
                --max-time 90 \
                "${api_url}" \
                --data-binary @"${request_file}" \
                > "${response_file}"; then
            echo "autoheal-analyze: curl failed for ${day_iso}" >&2
            rm -rf "${tmp_dir}"
            return 1
        fi
    fi

    # ---------------------------------------------------------------
    # Parse, validate, gate, persist.
    # ---------------------------------------------------------------

    local proposals_file
    proposals_file="$(proposals_dir)/${TODAY_ISO}.jsonl"
    mkdir -p "$(dirname "${proposals_file}")"

    local rejected_log
    rejected_log="$(logs_dir)/autoheal-rejected-${TODAY_ISO}.log"

    python3 - \
            "${response_file}" \
            "${proposals_file}" \
            "${rejected_log}" \
            "$(proposal_schema_path)" \
            "${CLONE_ID}" \
            "${CALIBRATION_MODE}" \
            "${day_iso}" \
            "$(cost_log_path)" \
            "${TODAY_ISO}" \
        <<'PY'
import datetime as dt
import json
import os
import sys

response_path = sys.argv[1]
proposals_path = sys.argv[2]
rejected_log = sys.argv[3]
schema_path = sys.argv[4]
clone_id = sys.argv[5]
calibration_mode = sys.argv[6] == "true"
day_iso = sys.argv[7]
cost_log_path = sys.argv[8]
today_iso = sys.argv[9]


def load_schema(path):
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def load_response(path):
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def extract_assistant_text(resp):
    """Return the assistant text from an Anthropic Messages response."""
    if not isinstance(resp, dict):
        return ""
    content = resp.get("content")
    if not isinstance(content, list):
        return ""
    parts = []
    for c in content:
        if isinstance(c, dict) and c.get("type") == "text":
            txt = c.get("text")
            if isinstance(txt, str):
                parts.append(txt)
    return "".join(parts)


def parse_proposals(text):
    text = text.strip()
    if not text:
        return []
    # Strip an optional code fence the model may emit despite the prompt.
    if text.startswith("```"):
        first_nl = text.find("\n")
        if first_nl != -1:
            text = text[first_nl + 1 :]
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()
    try:
        outer = json.loads(text)
    except json.JSONDecodeError:
        return []
    if not isinstance(outer, dict):
        return []
    proposals = outer.get("proposals")
    if not isinstance(proposals, list):
        return []
    return [p for p in proposals if isinstance(p, dict)]


def validate_against_schema(prop, schema):
    """Minimal schema check: required fields present, enum + numeric
    bounds respected. We deliberately avoid pulling in jsonschema."""
    required = schema.get("required", [])
    for k in required:
        if k not in prop:
            return False, f"missing required field: {k}"
    kind = prop.get("kind")
    enum = schema.get("properties", {}).get("kind", {}).get("enum", [])
    if enum and kind not in enum:
        return False, f"bad kind: {kind}"
    for nf, lo, hi in [
        ("confidence", 1, 10),
        ("breadth_score", 1, 10),
        ("occurrence_count", 1, None),
    ]:
        v = prop.get(nf)
        if not isinstance(v, int):
            return False, f"{nf} must be int"
        if hi is not None and not (lo <= v <= hi):
            return False, f"{nf} out of range [{lo},{hi}]"
        if hi is None and v < lo:
            return False, f"{nf} below min {lo}"
    sess = prop.get("session_ids")
    if not isinstance(sess, list) or not sess:
        return False, "session_ids must be non-empty list"
    return True, ""


def passes_privilege_gate(prop, calibration_mode):
    """plan.md §3.7 + §5 Epic 6 step 7.

    Steady state: reject when breadth_score >= 8 AND confidence < 9.
    Calibration: relax to breadth_score >= 10 AND confidence < 9
    (i.e. effectively allow breadth up to 9 with normal confidence)."""
    b = prop["breadth_score"]
    c = prop["confidence"]
    breadth_threshold = 10 if calibration_mode else 8
    if b >= breadth_threshold and c < 9:
        return False, f"breadth {b} >= {breadth_threshold} AND confidence {c} < 9"
    return True, ""


def append_jsonl(path, record):
    """Locked append using the same shape as hook_utils.file_locked_append.
    We call it here directly so we don't need to import the hook lib
    from a script that runs outside the hook environment."""
    import fcntl

    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    payload = json.dumps(record, ensure_ascii=False) + "\n"
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        try:
            os.write(fd, payload.encode("utf-8"))
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)


def log_rejection(path, prop, reason):
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    record = {
        "ts": dt.datetime.now(dt.timezone.utc).isoformat(),
        "reason": reason,
        "proposal": prop,
    }
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")


def append_cost(path, today, input_tokens, output_tokens, cost_usd):
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    line = f"{today}\t{input_tokens}\t{output_tokens}\t{cost_usd:.6f}\n"
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(line)


schema = load_schema(schema_path)
try:
    response = load_response(response_path)
except (OSError, json.JSONDecodeError) as exc:
    print(f"FATAL: cannot read response {response_path}: {exc}", file=sys.stderr)
    sys.exit(1)

# Cost accounting (best-effort; fixture responses may omit usage).
usage = response.get("usage") if isinstance(response, dict) else None
if isinstance(usage, dict):
    in_tok = int(usage.get("input_tokens", 0) or 0)
    out_tok = int(usage.get("output_tokens", 0) or 0)
else:
    in_tok = 0
    out_tok = 0
# Sonnet 4 pricing: $3/M in, $15/M out. Conservative — we under-report
# if the model id ever changes; tune in config if needed.
cost = (in_tok * 3.0 + out_tok * 15.0) / 1_000_000.0
append_cost(cost_log_path, today_iso, in_tok, out_tok, cost)

text = extract_assistant_text(response)
proposals = parse_proposals(text)

accepted = 0
rejected = 0

for prop in proposals:
    # Default originating_clone if the model omitted it.
    prop.setdefault("originating_clone", clone_id)
    prop.setdefault("generated_at", dt.datetime.now(dt.timezone.utc).isoformat())

    ok, why = validate_against_schema(prop, schema)
    if not ok:
        rejected += 1
        log_rejection(rejected_log, prop, f"schema: {why}")
        continue

    ok, why = passes_privilege_gate(prop, calibration_mode)
    if not ok:
        rejected += 1
        log_rejection(rejected_log, prop, f"privilege_gate: {why}")
        continue

    # Tag the source day so the digest can group by analysis date.
    prop.setdefault("source_day", day_iso)
    append_jsonl(proposals_path, prop)
    accepted += 1

print(json.dumps({
    "accepted": accepted,
    "rejected": rejected,
    "day": day_iso,
}))
PY
    local pa_rc=$?
    rm -rf "${tmp_dir}"
    if [ "${pa_rc}" -ne 0 ]; then
        echo "autoheal-analyze: post-API parse failed for ${day_iso} (rc=${pa_rc})" >&2
        return 1
    fi

    return 0
}

# ---------------------------------------------------------------------
# Loop over unanalyzed days.
# ---------------------------------------------------------------------

OVERALL_RC=0
while IFS= read -r day; do
    [ -z "${day}" ] && continue
    if ! analyze_one_day "${day}"; then
        OVERALL_RC=1
    fi
done <<< "${DAYS_TO_ANALYZE}"

# Bump last-analyzed regardless: subsequent runs should not re-process
# the same days even on partial failure (rejected days are logged).
printf '%s\n' "${TODAY_ISO}" > "$(last_analyzed_path)"

exit "${OVERALL_RC}"
