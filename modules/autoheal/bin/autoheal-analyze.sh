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
# CLI flags:
#   --force-day YYYY-MM-DD       Re-process exactly that day, ignoring
#                                 last-analyzed. Does not bump
#                                 last-analyzed. Useful when the cap was
#                                 raised or a clustering bug was fixed
#                                 and a previously-rejected day should
#                                 be retried.
#   --help                        Print usage and exit.
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
# CLI parsing.
# ---------------------------------------------------------------------

FORCE_DAY=""
while [ "$#" -gt 0 ]; do
    case "$1" in
        --force-day)
            shift
            if [ "$#" -eq 0 ]; then
                echo "autoheal-analyze: --force-day requires YYYY-MM-DD" >&2
                exit 1
            fi
            FORCE_DAY="$1"
            shift
            ;;
        --force-day=*)
            FORCE_DAY="${1#--force-day=}"
            shift
            ;;
        --help|-h)
            cat <<'USAGE'
Usage: autoheal-analyze.sh [--force-day YYYY-MM-DD]

Daily autoheal analyzer. By default processes every unanalyzed day in
the lookback window (default 7 days), bounded by ~/.claude/autoheal/last-analyzed.

Options:
  --force-day YYYY-MM-DD   Re-process exactly that day, ignoring
                           last-analyzed. Does not bump last-analyzed.
  --help                   Show this message.

See modules/autoheal/bin/autoheal-analyze.sh for full env-var docs.
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

# Validate --force-day format if set.
if [ -n "${FORCE_DAY}" ]; then
    if ! python3 -c "import datetime as dt; dt.date.fromisoformat('${FORCE_DAY}')" 2>/dev/null; then
        echo "autoheal-analyze: --force-day value '${FORCE_DAY}' is not a valid YYYY-MM-DD date" >&2
        exit 1
    fi
fi

# ---------------------------------------------------------------------
# Resolve module paths.
# ---------------------------------------------------------------------

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MODULE_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

# ---------------------------------------------------------------------
# Tunables (overridable via config; defaults match plan.md §3.7).
#
# The hard cap default rose from 40K to 200K in issue #517. Heavy event
# days (700+ events from cross-clone activity) were the most likely to
# contain proposal-worthy friction but were also the only ones that
# blew the previous 40K cap. 200K input @ Sonnet pricing is $0.60/day
# ceiling — well within the $1.00 daily_cost_cap_usd. Override via the
# config.json `max_input_tokens` key.
# ---------------------------------------------------------------------

MAX_INPUT_TOKENS_DEFAULT=200000     # Hard input cap (rough char/4 estimate).
MAX_INPUT_TOKENS="${MAX_INPUT_TOKENS_DEFAULT}"
DAILY_COST_CAP_CENTS_DEFAULT=100    # $1.00/day in cents.
DAILY_COST_CAP_CENTS="${DAILY_COST_CAP_CENTS_DEFAULT}"
DEFAULT_MODEL="claude-sonnet-4-6"   # Configurable in config.json.
DEFAULT_MAX_OUTPUT_TOKENS=4096
LOOKBACK_DAYS=7                     # Walk back at most this many days.
CALIBRATION_WINDOW_DAYS=7
REJECT_GIVEUP_THRESHOLD=7           # After N rejections of the same day,
                                    # give up and bump past it.

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

rejected_days_path() {
    printf '%s\n' "$(autoheal_dir)/rejected-days.jsonl"
}

# ---------------------------------------------------------------------
# Config-driven tunables (max_input_tokens, daily_cost_cap_usd).
#
# Reads ~/.claude/autoheal/config.json (or CCGM_AUTOHEAL_CONFIG). Missing
# file, malformed JSON, or missing keys fall back to defaults. Both
# values must be positive numbers; anything else is treated as missing.
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
        DEFAULT_MAX="${MAX_INPUT_TOKENS_DEFAULT}" \
        DEFAULT_CAP_CENTS="${DAILY_COST_CAP_CENTS_DEFAULT}" \
        python3 - <<'PY'
import json
import os

path = os.environ["CONFIG_PATH"]
default_max = int(os.environ["DEFAULT_MAX"])
default_cap_cents = int(os.environ["DEFAULT_CAP_CENTS"])

try:
    with open(path, "r", encoding="utf-8") as fh:
        cfg = json.load(fh)
except (OSError, json.JSONDecodeError):
    cfg = {}

if not isinstance(cfg, dict):
    cfg = {}

mit = cfg.get("max_input_tokens")
if isinstance(mit, (int, float)) and mit > 0:
    mit_out = int(mit)
else:
    mit_out = default_max

cap_usd = cfg.get("daily_cost_cap_usd")
if isinstance(cap_usd, (int, float)) and cap_usd > 0:
    cap_cents = int(round(float(cap_usd) * 100))
else:
    cap_cents = default_cap_cents

print(f"{mit_out}\t{cap_cents}")
PY
    )
    if [ -n "${parsed}" ]; then
        MAX_INPUT_TOKENS="$(printf '%s' "${parsed}" | cut -f1)"
        DAILY_COST_CAP_CENTS="$(printf '%s' "${parsed}" | cut -f2)"
    fi
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

# Apply config-driven tunables now that paths are resolved.
load_runtime_tunables

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

if [ -n "${FORCE_DAY}" ]; then
    # --force-day: process exactly this one day, ignoring last-analyzed.
    # Require an events file to exist for the day (otherwise there is
    # literally nothing to analyze).
    if [ ! -f "$(events_dir)/${FORCE_DAY}.jsonl" ]; then
        echo "autoheal-analyze: --force-day ${FORCE_DAY}: no events file at $(events_dir)/${FORCE_DAY}.jsonl" >&2
        exit 0
    fi
    DAYS_TO_ANALYZE="${FORCE_DAY}"
    echo "autoheal-analyze: --force-day ${FORCE_DAY}: ignoring last-analyzed, will NOT bump it." >&2
else
    DAYS_TO_ANALYZE="$(compute_days)"
fi

if [ -z "${DAYS_TO_ANALYZE}" ]; then
    echo "autoheal-analyze: no unanalyzed event days in the last ${LOOKBACK_DAYS} days." >&2
    if [ -z "${FORCE_DAY}" ]; then
        # Still bump last-analyzed so we don't keep re-scanning empty space.
        printf '%s\n' "${TODAY_ISO}" > "$(last_analyzed_path)"
    fi
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
# Rejection bookkeeping.
#
# When a day is rejected for size (rc=3 from pre-extract), append a
# record to ~/.claude/autoheal/rejected-days.jsonl and DO NOT bump
# last-analyzed past it. A subsequent run with a higher cap (or after
# the underlying clustering improves) will re-process the day.
#
# Days rejected >= REJECT_GIVEUP_THRESHOLD times are marked
# "give up" — the outer loop bumps past them so the analyzer doesn't
# loop indefinitely on a permanently-broken day.
# ---------------------------------------------------------------------

rejected_count_for_day() {
    # Counts prior rejections for `day` that match the CURRENT analyzer
    # version. A new analyzer (different short SHA) always starts the
    # retry counter at 0 — when a clustering / cap bug is fixed, days
    # rejected under the old code get a fresh chance under the new code
    # instead of being skipped forever. See issue #519 review.
    local day="$1"
    local version="$2"
    local path
    path="$(rejected_days_path)"
    if [ ! -f "${path}" ]; then
        printf '0\n'
        return 0
    fi
    REJ_DAY="${day}" REJ_VERSION="${version}" REJ_PATH="${path}" python3 - <<'PY'
import json
import os

path = os.environ["REJ_PATH"]
day = os.environ["REJ_DAY"]
version = os.environ["REJ_VERSION"]
n = 0
with open(path, "r", encoding="utf-8") as fh:
    for line in fh:
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(rec, dict) and rec.get("date") == day and rec.get("analyzer_version") == version:
            n += 1
print(n)
PY
}

record_rejection() {
    local day="$1"
    local est_tokens="$2"
    local cap="$3"
    local version="$4"
    local path
    path="$(rejected_days_path)"
    mkdir -p "$(dirname "${path}")"
    REJ_DAY="${day}" \
    REJ_EST="${est_tokens}" \
    REJ_CAP="${cap}" \
    REJ_VERSION="${version}" \
    REJ_PATH="${path}" \
    python3 - <<'PY'
import datetime as dt
import fcntl
import json
import os

path = os.environ["REJ_PATH"]
rec = {
    "date": os.environ["REJ_DAY"],
    "rejected_at": dt.datetime.now(dt.timezone.utc).isoformat(),
    "est_tokens": int(os.environ.get("REJ_EST") or 0),
    "max_input_tokens": int(os.environ.get("REJ_CAP") or 0),
    "analyzer_version": os.environ.get("REJ_VERSION") or "1",
}
parent = os.path.dirname(path)
if parent:
    os.makedirs(parent, exist_ok=True)
fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
try:
    fcntl.flock(fd, fcntl.LOCK_EX)
    try:
        os.write(fd, (json.dumps(rec, ensure_ascii=False) + "\n").encode("utf-8"))
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
finally:
    os.close(fd)
PY
}

analyzer_version() {
    # Best-effort: short git SHA for the current commit. Falls back to
    # "1" when not running inside a git checkout. The version label
    # exists so a future run can decide whether to retry a previously-
    # rejected day (i.e. the analyzer has changed since the rejection).
    local sha=""
    if command -v git >/dev/null 2>&1; then
        sha="$(git -C "${MODULE_ROOT}" rev-parse --short HEAD 2>/dev/null || true)"
    fi
    if [ -z "${sha}" ]; then
        printf '1\n'
    else
        printf '%s\n' "${sha}"
    fi
}

# Holds days rejected in this run (newline-separated). The outer loop
# uses this to gate the last-analyzed bump.
REJECTED_DAYS=""
GIVE_UP_DAYS=""

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
    """Load events with dedup on (session_id, timestamp, kind).

    The double-write contract — see hooks/failure-logger.py:8-12 — is that
    `failure-logger.py` and `permission-event-logger.py` both write a
    tool_failure record on the failure surface as redundancy guards. The
    analyzer dedupes here using the exact key the docstring promises.
    """
    out = []
    seen = set()
    n_dup = 0
    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(rec, dict):
                continue
            key = (
                rec.get("session_id") or "",
                rec.get("timestamp") or "",
                rec.get("kind") or "",
            )
            # Treat all-empty keys as non-deduppable (e.g. malformed rows).
            if key != ("", "", "") and key in seen:
                n_dup += 1
                continue
            if key != ("", "", ""):
                seen.add(key)
            out.append(rec)
    print(
        f"loaded {len(out)} unique events ({n_dup} duplicates skipped)",
        file=sys.stderr,
    )
    return out


def excerpt_transcript(transcript_path, around_ts, window=3):
    """Return up to `window` turns before and after `around_ts` from
    the user's session JSONL. Returns [] when the file is unreadable,
    the field is missing, or `window <= 0`."""
    if window <= 0:
        return []
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


def is_friction(ev):
    """An event is "friction" if it represents a stuck moment worth
    keeping as a full record. Routine successes are clustered instead.

    `permission_request` events are special: the bypass-suppress hook
    stamps auto-allows with `permission_decision: "allow"`, and those
    are the routine high-volume class — they MUST cluster, not get
    promoted to friction by virtue of their kind. Only deny/ask
    permission requests are friction (this matches the contract
    documented in analyzer-prompt.md §Event shape)."""
    kind = ev.get("kind")
    if kind in ("tool_failure", "user_correction", "realtime_security_alert"):
        return True
    exit_code = ev.get("exit_code")
    if isinstance(exit_code, int) and exit_code != 0:
        return True
    decision = ev.get("permission_decision")
    if decision in ("deny", "ask"):
        return True
    stderr = ev.get("stderr_excerpt")
    if isinstance(stderr, str) and stderr:
        return True
    return False


def signature(ev):
    """(tool_name, first 80 chars of redacted_command) for clustering."""
    tool = ev.get("tool_name") or ""
    cmd = ev.get("redacted_command") or ""
    if not isinstance(cmd, str):
        cmd = ""
    return (tool, cmd[:80])


def build_payload(events, window):
    """Return (runtime_context, events_list) for a given excerpt window.

    Friction events first (chronological by timestamp), then cluster
    records descending by `count`. Excerpts only attach to friction
    events; cluster records never carry transcript context."""
    friction_evs = [ev for ev in events if is_friction(ev)]
    routine_evs = [ev for ev in events if not is_friction(ev)]

    # Friction events: chronological, full record + adaptive excerpts.
    friction_evs.sort(key=lambda e: e.get("timestamp") or "")
    friction_records = []
    for ev in friction_evs:
        rec = {
            "kind": ev.get("kind"),
            "event": ev,
        }
        excerpts = excerpt_transcript(
            ev.get("transcript_path"),
            ev.get("timestamp") or ev.get("ts") or "",
            window=window,
        )
        if excerpts:
            rec["excerpts"] = excerpts
        friction_records.append(rec)

    # Routine events: group by signature; emit one cluster record per group
    # (including singletons — keeps shape consistent).
    groups = {}
    for ev in routine_evs:
        sig = signature(ev)
        g = groups.setdefault(sig, {
            "tool_name": sig[0],
            "redacted_command_prefix": sig[1],
            "count": 0,
            "first_seen": None,
            "last_seen": None,
            "sample_session_id": None,
        })
        g["count"] += 1
        ts = ev.get("timestamp") or ""
        if ts:
            if g["first_seen"] is None or ts < g["first_seen"]:
                g["first_seen"] = ts
            if g["last_seen"] is None or ts > g["last_seen"]:
                g["last_seen"] = ts
        if g["sample_session_id"] is None:
            g["sample_session_id"] = ev.get("session_id") or ""

    clusters = []
    for sig, g in groups.items():
        clusters.append({
            "kind": "cluster",
            "tool_name": g["tool_name"],
            "redacted_command_prefix": g["redacted_command_prefix"],
            "count": g["count"],
            "first_seen": g["first_seen"],
            "last_seen": g["last_seen"],
            "sample_session_id": g["sample_session_id"],
        })
    # Clusters descending by count (noisiest patterns first).
    clusters.sort(key=lambda c: c["count"], reverse=True)

    runtime_ctx = {
        "date": day_iso,
        "originating_clone": clone_id,
        "calibration_mode": calibration_mode,
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "event_summary": {
            "friction_events": len(friction_records),
            "cluster_records": len(clusters),
            "excerpt_window": window,
        },
    }
    return runtime_ctx, friction_records + clusters


events = load_events(events_file)

# Read the analyzer prompt.
try:
    with open(prompt_path, "r", encoding="utf-8") as fh:
        analyzer_prompt = fh.read()
except OSError as exc:
    print(f"FATAL: cannot read analyzer prompt at {prompt_path}: {exc}", file=sys.stderr)
    sys.exit(1)

# Adaptive excerpt window: try window=3 → 1 → 0 until under cap. Only
# reject the day if even window=0 (no excerpts at all) blows the cap —
# at which point the events themselves are too many for the configured
# budget.
final_window = None
final_runtime_ctx = None
final_events_list = None
serialized = None
est_tokens = None

for try_window in (3, 1, 0):
    rt_ctx, ev_list = build_payload(events, try_window)
    payload = {
        "runtime_context": rt_ctx,
        "events": ev_list,
    }
    s = json.dumps(payload, ensure_ascii=False)
    char_total = len(analyzer_prompt) + len(s)
    et = char_total // 4
    if et <= max_input_tokens:
        final_window = try_window
        final_runtime_ctx = rt_ctx
        final_events_list = ev_list
        serialized = s
        est_tokens = et
        break

if final_window is None:
    # Even window=0 was too big — the event list alone (post-dedup,
    # post-clustering) exceeds the input cap. Capture the over-cap
    # estimate against window=0 for the rejection log.
    rt_ctx, ev_list = build_payload(events, 0)
    payload = {
        "runtime_context": rt_ctx,
        "events": ev_list,
    }
    s = json.dumps(payload, ensure_ascii=False)
    char_total = len(analyzer_prompt) + len(s)
    est_tokens = char_total // 4
    print(
        f"WARN: estimated input tokens ({est_tokens}) > cap ({max_input_tokens}) "
        f"even at window=0; rejecting day {day_iso}",
        file=sys.stderr,
    )
    with open(os.path.join(tmp_dir, "REJECT_TOKEN_CAP"), "w", encoding="utf-8") as fh:
        fh.write(f"{est_tokens}\n")
    sys.exit(3)

print(f"excerpt window: {final_window}", file=sys.stderr)
print(f"estimated input tokens: {est_tokens} (cap {max_input_tokens})", file=sys.stderr)

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
        # Token cap rejected this day. Record the rejection and decide
        # whether to give up. See rejected_count_for_day / record_rejection.
        local est_tokens=""
        if [ -f "${tmp_dir}/REJECT_TOKEN_CAP" ]; then
            est_tokens="$(tr -d '\n' < "${tmp_dir}/REJECT_TOKEN_CAP" || true)"
        fi
        local version
        version="$(analyzer_version)"
        record_rejection "${day_iso}" "${est_tokens:-0}" "${MAX_INPUT_TOKENS}" "${version}"
        local prior
        prior="$(rejected_count_for_day "${day_iso}" "${version}")"
        # `prior` already includes this run's record (record_rejection
        # appended before the count). Anything >= threshold means we've
        # rejected this day enough times under THIS analyzer version to
        # give up. A future analyzer version starts the counter fresh.
        if [ "${prior}" -ge "${REJECT_GIVEUP_THRESHOLD}" ]; then
            echo "autoheal-analyze: GIVE_UP day=${day_iso} rejected ${prior} times; bumping past it." >&2
            GIVE_UP_DAYS="${GIVE_UP_DAYS}${day_iso}
"
        else
            REJECTED_DAYS="${REJECTED_DAYS}${day_iso}
"
        fi
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
            "$(config_path)" \
            "${DEFAULT_MODEL}" \
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
config_path = sys.argv[10]
fallback_model = sys.argv[11]


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


def append_locked(path, data):
    """Locked append using the same shape as hook_utils.file_locked_append.
    We inline the locking here so we don't need to import the hook lib
    from a script that runs outside the hook environment.

    Cross-clone-safe: fcntl.flock(LOCK_EX) on the open file descriptor
    serializes appends so concurrent writers from sibling clones cannot
    tear records mid-write.
    """
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


def append_jsonl(path, record):
    """Locked JSONL append. Convenience wrapper around append_locked."""
    append_locked(path, json.dumps(record, ensure_ascii=False))


def log_rejection(path, prop, reason):
    record = {
        "ts": dt.datetime.now(dt.timezone.utc).isoformat(),
        "reason": reason,
        "proposal": prop,
    }
    append_locked(path, json.dumps(record, ensure_ascii=False))


def append_cost(path, today, input_tokens, output_tokens, cost_usd, model):
    # `model` is appended as a 5th tab-separated field. Older cost.log
    # lines lacking this field still parse (today_cost_cents only reads
    # parts[0..3]); see issue #497.
    line = f"{today}\t{input_tokens}\t{output_tokens}\t{cost_usd:.6f}\t{model}"
    append_locked(path, line)


# Per-model pricing fallback. Matches autoheal-install.sh defaults; the
# install step is the source of truth, this dict only fires when the
# config file is unreadable or its cost_pricing block is missing entirely.
FALLBACK_PRICING = {
    "claude-sonnet-4-6": {"input_per_million": 3.0, "output_per_million": 15.0},
    "claude-opus-4-7": {"input_per_million": 15.0, "output_per_million": 75.0},
    "claude-haiku-4-5": {"input_per_million": 0.80, "output_per_million": 4.0},
}
SONNET_FALLBACK = FALLBACK_PRICING["claude-sonnet-4-6"]


def load_cfg(path):
    try:
        with open(path, "r", encoding="utf-8") as fh:
            cfg = json.load(fh)
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(cfg, dict):
        return {}
    return cfg


def resolve_pricing(cfg, fallback_model):
    """Return (model_id, pricing_dict). Emits a stderr warning when the
    configured model has no cost_pricing entry."""
    model = cfg.get("default_model") or cfg.get("model") or fallback_model
    pricing_map = cfg.get("cost_pricing")
    if not isinstance(pricing_map, dict):
        pricing_map = FALLBACK_PRICING
    pricing = pricing_map.get(model)
    if not isinstance(pricing, dict) or "input_per_million" not in pricing or "output_per_million" not in pricing:
        sys.stderr.write(
            f"WARNING: no cost_pricing for model {model}; "
            f"falling back to claude-sonnet-4-6 pricing\n"
        )
        pricing = SONNET_FALLBACK
    return model, pricing


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

cfg = load_cfg(config_path)
model_id, pricing = resolve_pricing(cfg, fallback_model)
cost = (
    in_tok * float(pricing["input_per_million"])
    + out_tok * float(pricing["output_per_million"])
) / 1_000_000.0
append_cost(cost_log_path, today_iso, in_tok, out_tok, cost, model_id)

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

# Bump last-analyzed (issue #517):
#  - --force-day mode never bumps (explicit user override).
#  - Otherwise, bump to TODAY unless we rejected a day during this run.
#  - When rejections happened, set last-analyzed to (earliest_rejected - 1)
#    so the next run retries the rejected day. Days that crossed the
#    give-up threshold are excluded from the rejected set so we DO
#    bump past them.
if [ -n "${FORCE_DAY}" ]; then
    : # --force-day: leave last-analyzed unchanged
elif [ -z "${REJECTED_DAYS}" ]; then
    printf '%s\n' "${TODAY_ISO}" > "$(last_analyzed_path)"
else
    # Pick the earliest still-retriable rejection.
    EARLIEST_REJECTED="$(printf '%s' "${REJECTED_DAYS}" | grep -v '^$' | sort | head -n 1)"
    if [ -n "${EARLIEST_REJECTED}" ]; then
        NEW_LAST="$(python3 -c "
import datetime as dt
d = dt.date.fromisoformat('${EARLIEST_REJECTED}') - dt.timedelta(days=1)
print(d.isoformat())
")"
        # If the earliest rejection is at/before our existing last-analyzed
        # we leave the file alone (would otherwise step backwards).
        CURRENT_LAST=""
        if [ -f "$(last_analyzed_path)" ]; then
            CURRENT_LAST="$(cat "$(last_analyzed_path)" 2>/dev/null | tr -d '\n')"
        fi
        if [ -z "${CURRENT_LAST}" ] || [ "${NEW_LAST}" \> "${CURRENT_LAST}" ]; then
            printf '%s\n' "${NEW_LAST}" > "$(last_analyzed_path)"
        fi
        echo "autoheal-analyze: rejected days this run: $(printf '%s' "${REJECTED_DAYS}" | tr '\n' ' '); last-analyzed=${NEW_LAST}" >&2
    fi
fi

exit "${OVERALL_RC}"
