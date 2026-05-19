#!/usr/bin/env bash
# autoheal-publish.sh
#
# Webhook publisher seam (plan.md §3.10, §5 Epic 12).
#
# Default state: webhook_url is null → script writes "webhook disabled
# (set webhook_url to enable)" to stderr and exits 0. No-op until a
# future dev.lem.work agent (a) deploys a /v1/ingest receiver and (b)
# tells the user the URL + token. The user adds them to config.json and
# the next daily run starts publishing.
#
# When webhook_url is set:
#   1. Diff today's proposals/events/digests against
#      ~/.claude/autoheal/published/{today}.last (cursor file). Cursor
#      records the count of records ALREADY PUBLISHED per kind.
#   2. For each new record (up to webhook_max_per_run), POST an envelope
#      to ${webhook_url}/v1/ingest with
#          Authorization: Bearer ${webhook_token}
#          Content-Type:  application/json
#      Envelope shape (plan.md §3.4):
#          {kind, ts, session_id, machine_id, data}
#      Idempotency: receiving endpoint expects (kind, machine_id, data.id)
#      to be unique; safe to re-POST.
#   3. On 2xx: advance cursor.
#   4. On 4xx/5xx: log to ~/.claude/logs/autoheal-publish-{today}.log;
#      DO NOT advance cursor (next daily run retries). NEVER fail the
#      pipeline; we always exit 0 so the daily wrapper continues.
#
# Env overrides (for tests):
#   CCGM_AUTOHEAL_DIR              default ~/.claude/autoheal
#   CCGM_AUTOHEAL_CONFIG           default $CCGM_AUTOHEAL_DIR/config.json
#   CCGM_AUTOHEAL_PROPOSALS_DIR    default $CCGM_AUTOHEAL_DIR/proposals
#   CCGM_AUTOHEAL_EVENTS_DIR       default $CCGM_AUTOHEAL_DIR/events
#   CCGM_AUTOHEAL_DIGESTS_DIR      default $CCGM_AUTOHEAL_DIR/digests
#   CCGM_AUTOHEAL_PUBLISHED_DIR    default $CCGM_AUTOHEAL_DIR/published
#   CCGM_AUTOHEAL_LOGS_DIR         default ~/.claude/logs
#   CCGM_AUTOHEAL_TODAY            default $(date +%Y-%m-%d)
#   CCGM_AUTOHEAL_MACHINE_ID       default `hostname`
#
# Exit codes:
#   0  always (failures are recorded in the log; never propagate)
#   2  invariant violation (jq/python3/curl missing)

set -u

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

AUTOHEAL_DIR="${CCGM_AUTOHEAL_DIR:-${HOME}/.claude/autoheal}"
CONFIG_FILE="${CCGM_AUTOHEAL_CONFIG:-${AUTOHEAL_DIR}/config.json}"
PROPOSALS_DIR="${CCGM_AUTOHEAL_PROPOSALS_DIR:-${AUTOHEAL_DIR}/proposals}"
EVENTS_DIR="${CCGM_AUTOHEAL_EVENTS_DIR:-${AUTOHEAL_DIR}/events}"
DIGESTS_DIR="${CCGM_AUTOHEAL_DIGESTS_DIR:-${AUTOHEAL_DIR}/digests}"
PUBLISHED_DIR="${CCGM_AUTOHEAL_PUBLISHED_DIR:-${AUTOHEAL_DIR}/published}"
LOGS_DIR="${CCGM_AUTOHEAL_LOGS_DIR:-${HOME}/.claude/logs}"
TODAY="${CCGM_AUTOHEAL_TODAY:-$(date +%Y-%m-%d)}"

PUBLISH_LOG="${LOGS_DIR}/autoheal-publish-${TODAY}.log"
CURSOR_FILE="${PUBLISHED_DIR}/${TODAY}.last"

# ---------------------------------------------------------------------------
# Preflight
# ---------------------------------------------------------------------------

if ! command -v jq >/dev/null 2>&1; then
    echo "ERROR: jq is required but not on PATH" >&2
    exit 2
fi
if ! command -v python3 >/dev/null 2>&1; then
    echo "ERROR: python3 is required but not on PATH" >&2
    exit 2
fi
if ! command -v curl >/dev/null 2>&1; then
    echo "ERROR: curl is required but not on PATH" >&2
    exit 2
fi

mkdir -p "${PUBLISHED_DIR}" "${LOGS_DIR}"

# ---------------------------------------------------------------------------
# Config: webhook_url, webhook_token, webhook_kinds, webhook_max_per_run
# ---------------------------------------------------------------------------

WEBHOOK_URL=""
WEBHOOK_TOKEN=""
WEBHOOK_KINDS_RAW=""
WEBHOOK_MAX=100

if [ -f "${CONFIG_FILE}" ]; then
    WEBHOOK_URL="$(jq -r '.webhook_url // empty' "${CONFIG_FILE}" 2>/dev/null || echo "")"
    WEBHOOK_TOKEN="$(jq -r '.webhook_token // empty' "${CONFIG_FILE}" 2>/dev/null || echo "")"
    WEBHOOK_KINDS_RAW="$(jq -r '(.webhook_kinds // ["proposal","event","digest"]) | .[]' "${CONFIG_FILE}" 2>/dev/null || echo "")"
    cfg_max="$(jq -r '.webhook_max_per_run // 100' "${CONFIG_FILE}" 2>/dev/null || echo "100")"
    case "${cfg_max}" in
        ''|*[!0-9]*) WEBHOOK_MAX=100 ;;
        *)           WEBHOOK_MAX="${cfg_max}" ;;
    esac
fi

if [ -z "${WEBHOOK_URL}" ]; then
    echo "webhook disabled (set webhook_url to enable)" >&2
    exit 0
fi

# Strip trailing slash so we can append /v1/ingest without doubling it.
WEBHOOK_URL="${WEBHOOK_URL%/}"
INGEST_URL="${WEBHOOK_URL}/v1/ingest"

# Default kind list if jq returned empty.
if [ -z "${WEBHOOK_KINDS_RAW}" ]; then
    WEBHOOK_KINDS_RAW=$'proposal\nevent\ndigest'
fi

# Build a lookup function so we can check kind membership cheaply.
kind_enabled() {
    local k="$1"
    printf '%s\n' "${WEBHOOK_KINDS_RAW}" | grep -qx "${k}"
}

MACHINE_ID="${CCGM_AUTOHEAL_MACHINE_ID:-$(hostname 2>/dev/null || python3 -c 'import socket; print(socket.gethostname())')}"

# ---------------------------------------------------------------------------
# Cursor: how many of each kind have already been published today.
# Format: simple TSV `kind\tcount` (so the file is editable + greppable
# and we don't need jq to read it).
# ---------------------------------------------------------------------------

read_cursor() {
    local kind="$1"
    if [ ! -f "${CURSOR_FILE}" ]; then
        echo "0"
        return
    fi
    local n
    n="$(awk -v k="${kind}" 'BEGIN{n=0} $1==k{n=$2} END{print n+0}' "${CURSOR_FILE}")"
    echo "${n:-0}"
}

write_cursor() {
    local kind="$1"
    local n="$2"
    local tmp="${CURSOR_FILE}.tmp.$$"
    if [ -f "${CURSOR_FILE}" ]; then
        awk -v k="${kind}" '$1!=k' "${CURSOR_FILE}" > "${tmp}"
    else
        : > "${tmp}"
    fi
    printf '%s\t%s\n' "${kind}" "${n}" >> "${tmp}"
    mv "${tmp}" "${CURSOR_FILE}"
}

log_line() {
    printf '[%s] %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$1" >> "${PUBLISH_LOG}"
}

# ---------------------------------------------------------------------------
# POST a single envelope. Echo HTTP status code to stdout. Echo nothing
# else (so callers can capture status cleanly). Body excerpt and status
# go to the publish log on non-2xx.
# ---------------------------------------------------------------------------

post_envelope() {
    local envelope="$1"
    local kind="$2"
    local rec_id="$3"

    local resp
    resp="$(mktemp -t autoheal-publish-resp.XXXXXX)"
    local http_code
    http_code="$(curl -sS -o "${resp}" -w "%{http_code}" \
        -X POST "${INGEST_URL}" \
        -H "Authorization: Bearer ${WEBHOOK_TOKEN}" \
        -H "Content-Type: application/json" \
        --data-binary "${envelope}" 2>>"${PUBLISH_LOG}" || echo "000")"

    case "${http_code}" in
        2*) : ;;
        *)
            {
                echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] webhook failure"
                echo "  kind: ${kind}"
                echo "  record_id: ${rec_id}"
                echo "  url: ${INGEST_URL}"
                echo "  http_code: ${http_code}"
                if [ -s "${resp}" ]; then
                    echo "  body_excerpt:"
                    head -c 512 "${resp}" | sed 's/^/    /'
                    echo ""
                fi
            } >> "${PUBLISH_LOG}"
            ;;
    esac

    rm -f "${resp}"
    echo "${http_code}"
}

# ---------------------------------------------------------------------------
# Iterate a JSONL source file from a starting offset; build envelope per
# record; POST; advance cursor on 2xx. Returns the new cursor value.
# Bounded by REMAINING_BUDGET (which decreases across kinds within one run).
# ---------------------------------------------------------------------------

REMAINING_BUDGET="${WEBHOOK_MAX}"
TOTAL_SENT=0
TOTAL_FAILED=0

publish_jsonl_kind() {
    local kind="$1"
    local src="$2"

    if ! kind_enabled "${kind}"; then
        return 0
    fi
    if [ ! -f "${src}" ]; then
        return 0
    fi

    local cursor; cursor="$(read_cursor "${kind}")"
    # Use awk to extract lines [cursor+1 .. cursor+REMAINING_BUDGET]. We
    # pipe each record into post_envelope; if it returns 2xx we advance
    # the cursor and continue, otherwise we STOP this kind (so the same
    # record retries next run; everything after it stays unpublished).
    local total_lines; total_lines="$(wc -l < "${src}" | tr -d ' ')"

    local idx="${cursor}"
    while [ "${idx}" -lt "${total_lines}" ] && [ "${REMAINING_BUDGET}" -gt 0 ]; do
        idx=$((idx + 1))
        local record
        record="$(sed -n "${idx}p" "${src}")"
        [ -z "${record}" ] && continue

        # Extract id, ts, session_id from the record. Defaults if absent.
        local rec_id rec_ts rec_session
        rec_id="$(printf '%s' "${record}" | jq -r '.id // empty' 2>/dev/null)"
        rec_ts="$(printf '%s' "${record}" | jq -r '.timestamp // .generated_at // empty' 2>/dev/null)"
        rec_session="$(printf '%s' "${record}" | jq -r '.session_id // empty' 2>/dev/null)"

        # If no id, synthesize one from a content hash so the envelope
        # still satisfies the receiving endpoint's idempotency contract.
        if [ -z "${rec_id}" ]; then
            rec_id="$(printf '%s' "${record}" | shasum -a 256 | awk '{print "auto_"substr($1,1,16)}')"
        fi

        # Build the envelope. The `data` field is the verbatim record
        # (parsed back into JSON so it's nested as an object, not a
        # double-encoded string).
        local envelope
        envelope="$(jq -nc \
            --arg kind "${kind}" \
            --arg ts "${rec_ts}" \
            --arg sid "${rec_session}" \
            --arg mid "${MACHINE_ID}" \
            --argjson data "${record}" \
            '{kind: $kind, ts: $ts, session_id: $sid, machine_id: $mid, data: $data}' 2>/dev/null)"

        if [ -z "${envelope}" ]; then
            # Malformed JSONL line — log + skip (do NOT advance the
            # cursor so a future fix lets us retry; but DO let the loop
            # progress past it by writing the skip to the log).
            log_line "skip kind=${kind} idx=${idx}: malformed record"
            # Advance cursor anyway — otherwise a single malformed line
            # blocks the rest of the kind forever. The downside is we
            # don't retry; the upside is the pipeline keeps moving.
            cursor="${idx}"
            write_cursor "${kind}" "${cursor}"
            continue
        fi

        local code
        code="$(post_envelope "${envelope}" "${kind}" "${rec_id}")"

        case "${code}" in
            2*)
                cursor="${idx}"
                write_cursor "${kind}" "${cursor}"
                REMAINING_BUDGET=$((REMAINING_BUDGET - 1))
                TOTAL_SENT=$((TOTAL_SENT + 1))
                ;;
            *)
                # Stop this kind on the first failure. Cursor is NOT
                # advanced, so the same record retries on the next run.
                TOTAL_FAILED=$((TOTAL_FAILED + 1))
                log_line "stop kind=${kind} at idx=${idx}: http=${code}"
                return 0
                ;;
        esac
    done

    return 0
}

# ---------------------------------------------------------------------------
# Digest is a single Markdown file, not JSONL. Treat it as a one-record
# stream: cursor=0 means "not yet published", cursor=1 means "published".
# ---------------------------------------------------------------------------

publish_digest() {
    if ! kind_enabled "digest"; then
        return 0
    fi
    local digest_file="${DIGESTS_DIR}/${TODAY}.md"
    if [ ! -f "${digest_file}" ]; then
        return 0
    fi
    if [ "${REMAINING_BUDGET}" -le 0 ]; then
        return 0
    fi

    local cursor; cursor="$(read_cursor "digest")"
    if [ "${cursor}" -ge 1 ]; then
        return 0  # Already published today.
    fi

    local body
    body="$(cat "${digest_file}")"
    local rec_id="digest_${TODAY}"
    local envelope
    envelope="$(jq -nc \
        --arg kind "digest" \
        --arg ts "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
        --arg mid "${MACHINE_ID}" \
        --arg date "${TODAY}" \
        --arg id "${rec_id}" \
        --arg body "${body}" \
        '{kind: $kind, ts: $ts, session_id: "", machine_id: $mid,
          data: {id: $id, date: $date, body: $body}}')"

    local code
    code="$(post_envelope "${envelope}" "digest" "${rec_id}")"
    case "${code}" in
        2*)
            write_cursor "digest" "1"
            REMAINING_BUDGET=$((REMAINING_BUDGET - 1))
            TOTAL_SENT=$((TOTAL_SENT + 1))
            ;;
        *)
            TOTAL_FAILED=$((TOTAL_FAILED + 1))
            log_line "stop kind=digest http=${code}"
            ;;
    esac
}

# ---------------------------------------------------------------------------
# Run the three streams in priority order: proposals first (most signal),
# then events, then digest.
# ---------------------------------------------------------------------------

publish_jsonl_kind "proposal" "${PROPOSALS_DIR}/${TODAY}.jsonl"
publish_jsonl_kind "event"    "${EVENTS_DIR}/${TODAY}.jsonl"
publish_digest

echo "autoheal-publish: ${TOTAL_SENT} sent; ${TOTAL_FAILED} failed; budget remaining=${REMAINING_BUDGET}" >&2
# Always exit 0 — failures are logged but never block the pipeline.
exit 0
