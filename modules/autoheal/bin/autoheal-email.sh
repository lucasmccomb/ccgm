#!/usr/bin/env bash
# autoheal-email.sh
#
# Optionally email today's autoheal digest via Resend.
#
# Behavior (plan.md §5 Epic 7 + §5 Epic 12 multi-recipient):
#   - email_enabled: false in config → exit 0 (no-op)
#   - RESEND_API_KEY required from env at runtime; warn-and-skip if absent
#   - digest_email config: string or list of strings
#   - For each recipient, per-recipient idempotency key:
#       ccgm-autoheal-{YYYY-MM-DD}-{sha256(recipient)[:12]}
#   - POST to https://api.resend.com/emails
#   - 2xx → write ~/.claude/autoheal/sent/{today}-{recipient-hash}.flag
#   - 4xx/5xx → log to ~/.claude/logs/autoheal-email-{today}.err.log; do NOT
#     fail the rest of the pipeline (Resend's idempotency means a retry on
#     the next daily run is safe)
#   - Analyzer crash detection: if today's proposals.jsonl missing AND
#     yesterday's was present, send a minimal diagnostic email with the most
#     recent autoheal.err.log tail (≤2KB, redacted).
#
# Env overrides (for tests):
#   CCGM_AUTOHEAL_PROPOSALS_DIR    default ~/.claude/autoheal/proposals
#   CCGM_AUTOHEAL_DIGESTS_DIR      default ~/.claude/autoheal/digests
#   CCGM_AUTOHEAL_SENT_DIR         default ~/.claude/autoheal/sent
#   CCGM_AUTOHEAL_LOGS_DIR         default ~/.claude/logs
#   CCGM_AUTOHEAL_CONFIG           default ~/.claude/autoheal/config.json
#   CCGM_AUTOHEAL_TODAY            default $(date +%Y-%m-%d)
#   CCGM_AUTOHEAL_RESEND_URL       default https://api.resend.com/emails
#                                  (tests point at a local mock server)
#   CCGM_AUTOHEAL_FROM             default "autoheal@ccgm.local"
#   CCGM_AUTOHEAL_LIB_DIR          default to in-tree modules/hooks/lib (when
#                                  running from the CCGM checkout), else
#                                  ~/.claude/lib (the installed copy)
#   CCGM_AUTOHEAL_ERR_LOG          default ~/.claude/logs/autoheal.err.log
#                                  (used for analyzer-crash diagnostic tail)
#
# Exit codes:
#   0  done (sent, skipped, or recorded failures non-fatally)
#   2  invariant violation (jq missing, python missing)

set -u

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

PROPOSALS_DIR="${CCGM_AUTOHEAL_PROPOSALS_DIR:-${HOME}/.claude/autoheal/proposals}"
DIGESTS_DIR="${CCGM_AUTOHEAL_DIGESTS_DIR:-${HOME}/.claude/autoheal/digests}"
SENT_DIR="${CCGM_AUTOHEAL_SENT_DIR:-${HOME}/.claude/autoheal/sent}"
LOGS_DIR="${CCGM_AUTOHEAL_LOGS_DIR:-${HOME}/.claude/logs}"
CONFIG_FILE="${CCGM_AUTOHEAL_CONFIG:-${HOME}/.claude/autoheal/config.json}"
TODAY="${CCGM_AUTOHEAL_TODAY:-$(date +%Y-%m-%d)}"
RESEND_URL="${CCGM_AUTOHEAL_RESEND_URL:-https://api.resend.com/emails}"
FROM_ADDR="${CCGM_AUTOHEAL_FROM:-autoheal@ccgm.local}"
ERR_LOG="${CCGM_AUTOHEAL_ERR_LOG:-${LOGS_DIR}/autoheal.err.log}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../../.." 2>/dev/null && pwd || echo "")"

if [ -n "${CCGM_AUTOHEAL_LIB_DIR:-}" ]; then
    LIB_DIR="${CCGM_AUTOHEAL_LIB_DIR}"
elif [ -n "${REPO_ROOT}" ] && [ -f "${REPO_ROOT}/modules/hooks/lib/hook_utils.py" ]; then
    LIB_DIR="${REPO_ROOT}/modules/hooks/lib"
else
    LIB_DIR="${HOME}/.claude/lib"
fi

DIGEST_FILE="${DIGESTS_DIR}/${TODAY}.md"
PROPOSALS_FILE="${PROPOSALS_DIR}/${TODAY}.jsonl"
EMAIL_ERR_LOG="${LOGS_DIR}/autoheal-email-${TODAY}.err.log"

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

mkdir -p "${SENT_DIR}" "${LOGS_DIR}"

# ---------------------------------------------------------------------------
# Config: email_enabled (default false) + digest_email (string or list)
# ---------------------------------------------------------------------------

email_enabled=0
recipients_raw=""
if [ -f "${CONFIG_FILE}" ]; then
    val="$(jq -r 'if has("email_enabled") then (.email_enabled | tostring) else "false" end' "${CONFIG_FILE}" 2>/dev/null || echo "false")"
    case "${val}" in
        true|1) email_enabled=1 ;;
    esac

    # Normalize digest_email into newline-delimited list. Strings stay 1
    # entry; arrays unpack to N entries; null/missing → empty.
    recipients_raw="$(jq -r '
        if has("digest_email") then
            if (.digest_email | type) == "array" then .digest_email[]
            elif (.digest_email | type) == "string" then .digest_email
            else empty
            end
        else empty end
    ' "${CONFIG_FILE}" 2>/dev/null || true)"
fi

if [ "${email_enabled}" -eq 0 ]; then
    echo "email disabled (email_enabled: false)" >&2
    exit 0
fi

if [ -z "${recipients_raw}" ]; then
    echo "email enabled but digest_email is unset; skipping" >&2
    exit 0
fi

if [ -z "${RESEND_API_KEY:-}" ]; then
    echo "RESEND_API_KEY not set in env; skipping email send" >&2
    exit 0
fi

# ---------------------------------------------------------------------------
# Analyzer crash detection
# ---------------------------------------------------------------------------
#
# Today's proposals file missing AND yesterday's present → send a minimal
# diagnostic email instead of the regular digest. The diagnostic body is the
# last ~2KB of the err log, redacted via hook_utils.redact_secrets.

is_crash_mode=0
crash_body=""

yesterday="$(CCGM_AUTOHEAL_TODAY="${TODAY}" python3 -c "
import datetime, os
today_str = os.environ['CCGM_AUTOHEAL_TODAY']
today = datetime.date.fromisoformat(today_str)
print((today - datetime.timedelta(days=1)).isoformat())
")"

yesterday_props="${PROPOSALS_DIR}/${yesterday}.jsonl"

if [ ! -f "${PROPOSALS_FILE}" ] && [ -f "${yesterday_props}" ]; then
    is_crash_mode=1
    crash_body="$(CCGM_ERR_LOG="${ERR_LOG}" CCGM_LIB_DIR="${LIB_DIR}" python3 - <<'PYEOF'
import os
import sys

sys.path.insert(0, os.environ["CCGM_LIB_DIR"])
try:
    from hook_utils import redact_secrets
except ImportError:
    def redact_secrets(text):
        return text

err_log = os.environ["CCGM_ERR_LOG"]
if not os.path.isfile(err_log):
    print("(no autoheal.err.log present)")
    sys.exit(0)

# Tail ~2KB.
size = os.path.getsize(err_log)
read_bytes = 2048
with open(err_log, "rb") as fh:
    if size > read_bytes:
        fh.seek(size - read_bytes)
    raw = fh.read()

try:
    text = raw.decode("utf-8", errors="replace")
except Exception:
    text = repr(raw)

# Drop a possibly-truncated first line.
if size > read_bytes and "\n" in text:
    text = text.split("\n", 1)[1]

print(redact_secrets(text))
PYEOF
    )"
fi

# ---------------------------------------------------------------------------
# Choose body: digest markdown OR crash diagnostic
# ---------------------------------------------------------------------------

if [ "${is_crash_mode}" -eq 1 ]; then
    SUBJECT="autoheal: analyzer crash diagnostic — ${TODAY}"
    BODY=$'**Autoheal analyzer did not produce proposals today.**\n\nMost recent autoheal.err.log tail (redacted):\n\n```\n'"${crash_body}"$'\n```\n'
else
    if [ ! -f "${DIGEST_FILE}" ]; then
        echo "no digest file at ${DIGEST_FILE}; skipping email" >&2
        exit 0
    fi
    SUBJECT="autoheal digest — ${TODAY}"
    BODY="$(cat "${DIGEST_FILE}")"
fi

# ---------------------------------------------------------------------------
# Send to each recipient with per-recipient idempotency key
# ---------------------------------------------------------------------------

errors=0
sent=0
total=0

# Iterate recipients via newline-delimited; preserve whitespace-safe behavior.
# Use process substitution to feed the while loop so counters are not in a
# subshell.
while IFS= read -r recipient; do
    [ -z "${recipient}" ] && continue
    total=$((total + 1))

    # 12-char sha256 prefix of the recipient.
    rec_hash="$(printf '%s' "${recipient}" | shasum -a 256 | awk '{print substr($1, 1, 12)}')"
    idem_key="ccgm-autoheal-${TODAY}-${rec_hash}"
    sent_flag="${SENT_DIR}/${TODAY}-${rec_hash}.flag"

    # Build JSON payload via jq (so the body is safely escaped).
    payload="$(jq -nc \
        --arg from "${FROM_ADDR}" \
        --arg to "${recipient}" \
        --arg subject "${SUBJECT}" \
        --arg text "${BODY}" \
        '{
            from: $from,
            to: [$to],
            subject: $subject,
            text: $text
        }')"

    # Capture HTTP status separately from body.
    response_file="$(mktemp -t autoheal-email-resp.XXXXXX)"
    http_code="$(curl -sS -o "${response_file}" -w "%{http_code}" \
        -X POST "${RESEND_URL}" \
        -H "Authorization: Bearer ${RESEND_API_KEY}" \
        -H "Content-Type: application/json" \
        -H "Idempotency-Key: ${idem_key}" \
        --data-binary "${payload}" 2>>"${EMAIL_ERR_LOG}" || echo "000")"

    case "${http_code}" in
        2*)
            sent=$((sent + 1))
            # Record send so the digest backfill skips this day for this
            # recipient on subsequent runs.
            : > "${sent_flag}"
            ;;
        *)
            errors=$((errors + 1))
            {
                echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] resend failure"
                echo "  recipient: ${recipient}"
                echo "  http_code: ${http_code}"
                echo "  idempotency_key: ${idem_key}"
                if [ -s "${response_file}" ]; then
                    echo "  body_excerpt:"
                    head -c 1024 "${response_file}" | sed 's/^/    /'
                    echo ""
                fi
            } >> "${EMAIL_ERR_LOG}"
            ;;
    esac

    rm -f "${response_file}"
done <<EOF
${recipients_raw}
EOF

echo "autoheal-email: ${sent}/${total} sent; ${errors} errors" >&2
# Exit 0 always — Resend's idempotency means retries on the next daily run
# are safe; we do not want a single recipient failure to kill the pipeline.
exit 0
