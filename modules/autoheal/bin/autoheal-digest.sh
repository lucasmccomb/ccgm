#!/usr/bin/env bash
# autoheal-digest.sh
#
# Render today's autoheal proposals into a markdown digest at
# ~/.claude/autoheal/digests/{today}.md.
#
# Behavior (plan.md §5 Epic 7):
#   - Local digest is always-on. Config `digest_enabled: false` skips.
#   - Caps at 5 proposals/day; remainder summarized as "+N more".
#   - Empty proposals: skip (exit 0) unless --include-empty.
#   - Backfill summary: list unemailed days from the past 7 (sent flags
#     missing under ~/.claude/autoheal/sent/).
#   - Redaction: rationale and title pass through
#     hook_utils.redact_secrets() BEFORE rendering.
#   - Footer links to /autoheal-toggle, /autoheal-snooze, /autoheal-apply list.
#
# Env overrides (for tests):
#   CCGM_AUTOHEAL_PROPOSALS_DIR    default ~/.claude/autoheal/proposals
#   CCGM_AUTOHEAL_DIGESTS_DIR      default ~/.claude/autoheal/digests
#   CCGM_AUTOHEAL_SENT_DIR         default ~/.claude/autoheal/sent
#   CCGM_AUTOHEAL_CONFIG           default ~/.claude/autoheal/config.json
#   CCGM_AUTOHEAL_TODAY            default $(date -u +%Y-%m-%d). UTC-keyed
#                                  to match proposals/{date}.jsonl written
#                                  by the analyzer (issue #520).
#   CCGM_AUTOHEAL_LIB_DIR          default to in-tree modules/hooks/lib (when
#                                  running from the CCGM checkout), else
#                                  ~/.claude/lib (the installed copy).
#
# Exit codes:
#   0  digest rendered, or skipped cleanly (empty / disabled)
#   2  invariant violation (jq missing, python missing, bad config)

set -u

# ---------------------------------------------------------------------------
# Args
# ---------------------------------------------------------------------------

INCLUDE_EMPTY=0
while [ $# -gt 0 ]; do
    case "$1" in
        --include-empty)
            INCLUDE_EMPTY=1
            shift
            ;;
        -h|--help)
            cat <<EOF
Usage: $0 [--include-empty]

Render today's autoheal proposals into a markdown digest.
EOF
            exit 0
            ;;
        *)
            echo "ERROR: unknown argument: $1" >&2
            exit 2
            ;;
    esac
done

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

PROPOSALS_DIR="${CCGM_AUTOHEAL_PROPOSALS_DIR:-${HOME}/.claude/autoheal/proposals}"
DIGESTS_DIR="${CCGM_AUTOHEAL_DIGESTS_DIR:-${HOME}/.claude/autoheal/digests}"
SENT_DIR="${CCGM_AUTOHEAL_SENT_DIR:-${HOME}/.claude/autoheal/sent}"
CONFIG_FILE="${CCGM_AUTOHEAL_CONFIG:-${HOME}/.claude/autoheal/config.json}"
TODAY="${CCGM_AUTOHEAL_TODAY:-$(date -u +%Y-%m-%d)}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../../.." 2>/dev/null && pwd || echo "")"

if [ -n "${CCGM_AUTOHEAL_LIB_DIR:-}" ]; then
    LIB_DIR="${CCGM_AUTOHEAL_LIB_DIR}"
elif [ -n "${REPO_ROOT}" ] && [ -f "${REPO_ROOT}/modules/hooks/lib/hook_utils.py" ]; then
    LIB_DIR="${REPO_ROOT}/modules/hooks/lib"
else
    LIB_DIR="${HOME}/.claude/lib"
fi

PROPOSALS_FILE="${PROPOSALS_DIR}/${TODAY}.jsonl"
DIGEST_FILE="${DIGESTS_DIR}/${TODAY}.md"

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

mkdir -p "${DIGESTS_DIR}"

# ---------------------------------------------------------------------------
# Config: digest_enabled (default true)
# ---------------------------------------------------------------------------

digest_enabled=1
if [ -f "${CONFIG_FILE}" ]; then
    val="$(jq -r 'if has("digest_enabled") then (.digest_enabled | tostring) else "true" end' "${CONFIG_FILE}" 2>/dev/null || echo "true")"
    case "${val}" in
        false|0|"") digest_enabled=0 ;;
    esac
fi

if [ "${digest_enabled}" -eq 0 ]; then
    echo "digest disabled (digest_enabled: false in ${CONFIG_FILE})" >&2
    exit 0
fi

# ---------------------------------------------------------------------------
# Proposal count
# ---------------------------------------------------------------------------

proposal_count=0
if [ -f "${PROPOSALS_FILE}" ]; then
    # Count non-blank lines.
    proposal_count="$(grep -c . "${PROPOSALS_FILE}" 2>/dev/null || echo 0)"
fi

if [ "${proposal_count}" -eq 0 ] && [ "${INCLUDE_EMPTY}" -eq 0 ]; then
    echo "no proposals for ${TODAY}; skipping digest" >&2
    exit 0
fi

# ---------------------------------------------------------------------------
# Backfill: unemailed days in past 7 (sent flags missing)
# ---------------------------------------------------------------------------
#
# A day is considered "unemailed" if BOTH:
#   (a) a proposals file exists for that day (we have something to email)
#   (b) no sent flag matching ${SENT_DIR}/${date}*.flag exists
#
# We look back 7 days INCLUDING yesterday (not today; today is the active
# digest, not a backfill candidate).

backfill_days=""
i=1
while [ ${i} -le 7 ]; do
    # Cross-platform date arithmetic. macOS BSD date and GNU date differ;
    # python is the portable hammer.
    past_date="$(CCGM_OFFSET="${i}" python3 -c "
import datetime, os
offset = int(os.environ['CCGM_OFFSET'])
today_str = os.environ.get('CCGM_AUTOHEAL_TODAY', '') or datetime.datetime.now(datetime.timezone.utc).date().isoformat()
today = datetime.date.fromisoformat(today_str)
print((today - datetime.timedelta(days=offset)).isoformat())
" CCGM_AUTOHEAL_TODAY="${TODAY}")"

    past_proposals="${PROPOSALS_DIR}/${past_date}.jsonl"
    if [ -f "${past_proposals}" ] && [ "$(grep -c . "${past_proposals}" 2>/dev/null || echo 0)" -gt 0 ]; then
        sent_glob="${SENT_DIR}/${past_date}"
        if ! ls "${sent_glob}"*.flag >/dev/null 2>&1; then
            if [ -z "${backfill_days}" ]; then
                backfill_days="${past_date}"
            else
                backfill_days="${backfill_days} ${past_date}"
            fi
        fi
    fi
    i=$((i + 1))
done

# ---------------------------------------------------------------------------
# Render digest
# ---------------------------------------------------------------------------
#
# We pipe the proposals file plus state through a Python helper that handles:
#   - JSON parsing per line
#   - field redaction via hook_utils.redact_secrets()
#   - 5-cap + "+N more" summary
#   - markdown rendering
# Bash + jq is too cumbersome for templated multi-line markdown.

OUTPUT="$(
    CCGM_PROPOSALS_FILE="${PROPOSALS_FILE}" \
    CCGM_DIGEST_TODAY="${TODAY}" \
    CCGM_BACKFILL_DAYS="${backfill_days}" \
    CCGM_LIB_DIR="${LIB_DIR}" \
    CCGM_INCLUDE_EMPTY="${INCLUDE_EMPTY}" \
    python3 - <<'PYEOF'
import json
import os
import sys

sys.path.insert(0, os.environ["CCGM_LIB_DIR"])
try:
    from hook_utils import redact_secrets
except ImportError:
    def redact_secrets(text):
        return text

proposals_file = os.environ["CCGM_PROPOSALS_FILE"]
today = os.environ["CCGM_DIGEST_TODAY"]
backfill_days = [d for d in os.environ.get("CCGM_BACKFILL_DAYS", "").split() if d]
include_empty = os.environ.get("CCGM_INCLUDE_EMPTY", "0") == "1"

proposals = []
if os.path.isfile(proposals_file):
    with open(proposals_file, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                proposals.append(json.loads(line))
            except json.JSONDecodeError:
                # Skip malformed lines silently; the analyzer guarantees
                # well-formed lines and a malformed line here is a sign
                # of corruption that the analyzer test suite covers.
                continue


def safe(record, key, default=""):
    val = record.get(key)
    return val if val is not None else default


def render_proposal(p):
    title = redact_secrets(str(safe(p, "title", "(untitled)")))
    rationale = redact_secrets(str(safe(p, "rationale", "")))
    pid = safe(p, "id", "(no-id)")
    kind = safe(p, "kind", "(no-kind)")
    confidence = safe(p, "confidence", "?")
    breadth = safe(p, "breadth_score", "?")
    occ = safe(p, "occurrence_count", "?")

    lines = [
        f"### {title}",
        "",
        f"- **id**: `{pid}`",
        f"- **kind**: `{kind}`",
        f"- **confidence**: {confidence}/10",
        f"- **breadth**: {breadth}/10",
        f"- **occurrences**: {occ}",
        "",
        "**Rationale**",
        "",
    ]
    if rationale:
        for ln in rationale.splitlines() or [rationale]:
            lines.append(ln)
    else:
        lines.append("_(no rationale provided)_")
    lines.append("")
    lines.append(f"Apply: `/autoheal-apply {pid}`")
    lines.append("")
    return "\n".join(lines)


# Stable order: confidence desc, then occurrence_count desc, then id asc.
def sort_key(p):
    return (
        -(int(p.get("confidence") or 0)),
        -(int(p.get("occurrence_count") or 0)),
        str(p.get("id") or ""),
    )


proposals.sort(key=sort_key)

CAP = 5
shown = proposals[:CAP]
hidden = proposals[CAP:]

out = []
out.append(f"# Autoheal digest — {today}")
out.append("")
if not proposals:
    if not include_empty:
        # Should not reach here; the bash caller short-circuits on empty
        # without --include-empty.
        sys.exit(0)
    out.append("_No proposals for today._")
    out.append("")
else:
    summary_line = f"_{len(proposals)} proposal"
    summary_line += "s_" if len(proposals) != 1 else "_"
    out.append(summary_line)
    out.append("")
    for p in shown:
        out.append(render_proposal(p))
    if hidden:
        n = len(hidden)
        plural = "proposal" if n == 1 else "proposals"
        out.append(
            f"+{n} more {plural} — see `/autoheal-digest {today}` for the full list."
        )
        out.append("")

if backfill_days:
    out.append("## Backfill — unemailed days (past 7)")
    out.append("")
    for d in backfill_days:
        out.append(f"- `{d}` — see `/autoheal-digest {d}`")
    out.append("")

out.append("---")
out.append("")
out.append("**Controls**")
out.append("")
out.append("- `/autoheal-toggle [pause|resume|status|realtime|autoapply|webhook]`")
out.append("- `/autoheal-snooze <id> [days]`")
out.append("- `/autoheal-apply list`")
out.append("")

sys.stdout.write("\n".join(out))
PYEOF
)"

py_exit=$?
if [ ${py_exit} -ne 0 ]; then
    echo "ERROR: digest renderer failed (exit ${py_exit})" >&2
    exit 2
fi

if [ -z "${OUTPUT}" ]; then
    # Render produced no body and caller did not request --include-empty.
    echo "digest renderer produced empty output; not writing ${DIGEST_FILE}" >&2
    exit 0
fi

printf '%s\n' "${OUTPUT}" > "${DIGEST_FILE}"
echo "digest written: ${DIGEST_FILE}" >&2
exit 0
