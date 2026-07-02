#!/usr/bin/env bash
# CCGM dreaming — digest renderer (Epic 3).
#
# Renders a markdown digest for one day to
# ~/.claude/dreaming/digests/{date}.md, combining:
#   - that day's proposals (~/.claude/dreaming/proposals/{date}.jsonl),
#     grouped by project/kind, with evidence excerpts, prevalence, and
#     confidence; needs_manual_promotion / compaction_guard_failed flags
#     rendered inline (never hidden).
#   - that day's run summary (~/.claude/dreaming/state/runs/{date}.json),
#     if dream-analyze.sh produced one -- call counts, cost estimate,
#     slugs skipped and why.
#   - the DURABLE canary state (~/.claude/dreaming/state/canary.json),
#     read unconditionally regardless of which date is being rendered: a
#     loud banner when any schema_canary incident is still active, or when
#     any untested transcript-schema version has been observed
#     (adrev-014 + the #753 handoff note -- both signals must stay visible
#     even if a human misses the exact day they first appeared, since
#     Epic 6's dream-daily.sh chain is exit-tolerant and can swallow a
#     non-zero exit silently).
#   - yesterday's proposals, tallied by status (accepted/auto_applied vs
#     rejected) -- forward-compatible with Epic 6's /dream-apply, which is
#     the only future writer of any status other than "pending".
#
# Unlike autoheal-digest.sh, this renderer never skips on an empty day:
# the canary banner must be checkable on any date, including a day with
# zero proposals.
#
# Usage:
#   dream-digest.sh [YYYY-MM-DD]     # defaults to CCGM_DREAMING_TODAY or today (UTC)
#
# Exit codes:
#   0  digest rendered
#   2  invariant violation (python3 missing, bad date argument)

set -u

DATE_ARG="${1:-}"

if [ -n "${DATE_ARG}" ]; then
    if ! python3 -c "import datetime as dt, sys; dt.date.fromisoformat(sys.argv[1])" "${DATE_ARG}" 2>/dev/null; then
        echo "dream-digest: '${DATE_ARG}' is not a valid YYYY-MM-DD date" >&2
        exit 2
    fi
    TARGET_DATE="${DATE_ARG}"
else
    TARGET_DATE="${CCGM_DREAMING_TODAY:-$(python3 -c 'import datetime; print(datetime.datetime.now(datetime.timezone.utc).date().isoformat())')}"
fi

DREAMING_DIR="${CCGM_DREAMING_DIR:-${HOME}/.claude/dreaming}"
PROPOSALS_DIR="${DREAMING_DIR}/proposals"
DIGESTS_DIR="${DREAMING_DIR}/digests"
STATE_DIR="${DREAMING_DIR}/state"

if ! command -v python3 >/dev/null 2>&1; then
    echo "dream-digest: python3 not found on PATH" >&2
    exit 2
fi

mkdir -p "${DIGESTS_DIR}"

YESTERDAY="$(python3 -c "
import datetime as dt
d = dt.date.fromisoformat('${TARGET_DATE}') - dt.timedelta(days=1)
print(d.isoformat())
")"

OUTPUT="$(
    CCGM_DIGEST_TARGET_DATE="${TARGET_DATE}" \
    CCGM_DIGEST_YESTERDAY="${YESTERDAY}" \
    CCGM_DIGEST_PROPOSALS_FILE="${PROPOSALS_DIR}/${TARGET_DATE}.jsonl" \
    CCGM_DIGEST_YESTERDAY_PROPOSALS_FILE="${PROPOSALS_DIR}/${YESTERDAY}.jsonl" \
    CCGM_DIGEST_RUN_SUMMARY_FILE="${STATE_DIR}/runs/${TARGET_DATE}.json" \
    CCGM_DIGEST_CANARY_FILE="${STATE_DIR}/canary.json" \
    python3 - <<'PYEOF'
import json
import os

target_date = os.environ["CCGM_DIGEST_TARGET_DATE"]
yesterday = os.environ["CCGM_DIGEST_YESTERDAY"]


def load_jsonl(path):
    rows = []
    if not os.path.isfile(path):
        return rows
    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return rows


def load_json(path, default):
    if not os.path.isfile(path):
        return default
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, json.JSONDecodeError):
        return default


proposals = load_jsonl(os.environ["CCGM_DIGEST_PROPOSALS_FILE"])
yesterday_proposals = load_jsonl(os.environ["CCGM_DIGEST_YESTERDAY_PROPOSALS_FILE"])
run_summary = load_json(os.environ["CCGM_DIGEST_RUN_SUMMARY_FILE"], None)
canary = load_json(os.environ["CCGM_DIGEST_CANARY_FILE"], {"active_incidents": {}, "untested_versions_observed": {}})

out = []
out.append(f"# Dreaming digest — {target_date}")
out.append("")

# --- Durable canary banner (adrev-014 + #753 handoff) ----------------------
active_incidents = canary.get("active_incidents") or {}
untested_versions = canary.get("untested_versions_observed") or {}
if active_incidents or untested_versions:
    out.append("## ⚠️ Canary banner (durable — shown until acknowledged)")
    out.append("")
    if active_incidents:
        out.append("**schema_canary fired for:**")
        out.append("")
        for slug, info in sorted(active_incidents.items()):
            out.append(f"- `{slug}` (first seen {info.get('date', '?')}): {info.get('detail', '')}")
        out.append("")
    if untested_versions:
        out.append("**Untested transcript-schema versions observed:**")
        out.append("")
        for version, count in sorted(untested_versions.items()):
            out.append(f"- `{version}` — {count} session(s)")
        out.append("")

# --- Run summary -------------------------------------------------------------
if run_summary is not None:
    out.append("## Run summary")
    out.append("")
    out.append(f"- offline: {run_summary.get('offline', False)}")
    out.append(f"- slugs considered: {len(run_summary.get('slugs_considered', []))}")
    out.append(f"- slugs planned this run: {len(run_summary.get('slugs_planned', []))}")
    skip_reasons = run_summary.get("skip_reasons") or {}
    if skip_reasons:
        out.append("- skipped:")
        for slug, reason in sorted(skip_reasons.items()):
            out.append(f"  - `{slug}`: {reason}")
    out.append(f"- map calls: {run_summary.get('map_calls', 0)}, reduce calls: {run_summary.get('reduce_calls', 0)}")
    cost = run_summary.get("cost_breakdown") or {}
    if cost:
        out.append(
            f"- estimated cost: ${cost.get('estimated_total_cost_usd', 0):.4f} "
            f"(remaining budget at plan time: ${cost.get('remaining_budget_usd', 0):.4f})"
        )
    out.append(f"- proposals: {run_summary.get('proposals_written', 0)} written, "
                f"{run_summary.get('proposals_rejected', 0)} rejected, "
                f"{run_summary.get('proposals_deduped', 0)} deduped")
    out.append("")
else:
    out.append("_No analysis run recorded for this date._")
    out.append("")


def render_evidence(evidence):
    lines = []
    for e in (evidence or [])[:3]:
        sid = e.get("session_id") or "(unknown session)"
        excerpt = e.get("excerpt") or ""
        lines.append(f"  - `{sid}`: {excerpt}")
    return lines


def render_proposal(p):
    kind = p.get("kind", "(no-kind)")
    pid = p.get("id", "(no-id)")
    confidence = p.get("confidence", "?")
    prevalence = p.get("prevalence") or {}
    lines = [
        f"#### {kind} — `{pid}`",
        "",
        f"- **status**: {p.get('status', 'pending')}",
        f"- **confidence**: {confidence}/10",
        f"- **prevalence**: sessions={prevalence.get('sessions', '?')}, agents={prevalence.get('agents', '?')}",
    ]
    if p.get("target_id"):
        lines.append(f"- **target_id**: `{p['target_id']}`")
    if p.get("needs_manual_promotion"):
        lines.append(f"- ⚠️ **needs_manual_promotion**: {p['needs_manual_promotion']}")
    if p.get("compaction_guard_failed"):
        dropped = p["compaction_guard_failed"].get("dropped_tokens", [])
        lines.append(f"- ⚠️ **compaction_guard_failed**: dropped fact tokens: {dropped}")
    if p.get("content"):
        lines.append(f"- **content**: {p['content']}")
    lines.append(f"- **justification**: {p.get('justification', '')}")
    ev_lines = render_evidence(p.get("evidence"))
    if ev_lines:
        lines.append("- **evidence**:")
        lines.extend(ev_lines)
    lines.append("")
    lines.append(f"Apply: `/dream-apply {pid}`")
    lines.append("")
    return "\n".join(lines)


out.append("## Proposals")
out.append("")
if not proposals:
    out.append("_No proposals for this date._")
    out.append("")
else:
    pending = sum(1 for p in proposals if p.get("status", "pending") == "pending")
    out.append(f"_{len(proposals)} proposal(s), {pending} pending._")
    out.append("")

    grouped = {}
    for p in proposals:
        grouped.setdefault(p.get("project", "(unknown)"), []).append(p)

    for project in sorted(grouped):
        out.append(f"### {project}")
        out.append("")
        rows = sorted(grouped[project], key=lambda p: (-(int(p.get("confidence") or 0)), p.get("id", "")))
        for p in rows:
            out.append(render_proposal(p))

# --- Yesterday's applied/rejected tally --------------------------------------
out.append("## Yesterday's tally")
out.append("")
if not yesterday_proposals:
    out.append(f"_No proposals recorded for {yesterday}._")
    out.append("")
else:
    applied = sum(1 for p in yesterday_proposals if p.get("status") in ("accepted", "auto_applied"))
    rejected = sum(1 for p in yesterday_proposals if p.get("status") == "rejected")
    pending = sum(1 for p in yesterday_proposals if p.get("status", "pending") == "pending")
    out.append(f"- `{yesterday}`: {applied} applied, {rejected} rejected, {pending} still pending "
                f"(of {len(yesterday_proposals)} total)")
    out.append("")

out.append("---")
out.append("")
out.append("**Controls**")
out.append("")
out.append("- `/dream` — status")
out.append(f"- `/dream-digest {target_date}` — re-render this digest")
out.append("- `/dream-apply list` — list pending proposals")
out.append("")

print("\n".join(out))
PYEOF
)"

py_exit=$?
if [ ${py_exit} -ne 0 ]; then
    echo "dream-digest: renderer failed (exit ${py_exit})" >&2
    exit 2
fi

DIGEST_FILE="${DIGESTS_DIR}/${TARGET_DATE}.md"
printf '%s\n' "${OUTPUT}" > "${DIGEST_FILE}"
echo "digest written: ${DIGEST_FILE}" >&2
exit 0
