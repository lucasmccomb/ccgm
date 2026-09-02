#!/usr/bin/env bash
# CCGM dreaming — digest renderer (Epic 3; "Applied this run (auto)" section
# added by optimistic-memory plan.md Epic 5).
#
# Renders a markdown digest for one day to
# ~/.claude/dreaming/digests/{date}.md, combining:
#   - "Applied this run (auto)" (Epic 5): TODAY's own optimistic-integration
#     batch(es) -- rows Epic 3's engine auto-applied (status: auto_applied)
#     carrying a batch_id, posture, and (for dwell postures) dwell_until.
#     The nightly chain now runs optimistic-integrate BEFORE this digest
#     (dream-daily.sh), so this always reports a batch whose dwell window
#     is still entirely ahead of it. Grouped by project/kind; action items
#     (rows still mid-dwell, any anomaly-skipped slug, a tripped breaker
#     banner) render before routine confirmations; every row carries a
#     one-line undo command. Silent when nothing NEW was auto-applied --
#     no heading at all in that case (a digest that fires on empty nights
#     trains the reader to ignore it). A per-batch "already surfaced"
#     marker (~/.claude/dreaming/state/surfaced/<batch_id>.json) means a
#     batch is shown exactly once, ever, in the report for its own day --
#     re-rendering the same day (or, defensively, a batch_id that resurfaces
#     in a later day's file) is a no-op once shown.
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
#     a reduce-phase parse failure is unresolved (adrev-014 + the #753
#     handoff note -- both signals must stay visible even if a human
#     misses the exact day they first appeared, since Epic 6's
#     dream-daily.sh chain is exit-tolerant and can swallow a non-zero
#     exit silently).
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

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MODULE_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

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
    CCGM_DIGEST_APPLY_AUDIT_FILE="${STATE_DIR}/apply-audit.jsonl" \
    CCGM_DIGEST_SURFACED_DIR="${STATE_DIR}/surfaced" \
    CCGM_DIGEST_MODULE_ROOT="${MODULE_ROOT}" \
    python3 - <<'PYEOF'
import datetime as _dt
import json
import os
import subprocess
import sys
from pathlib import Path

# Render-time defense-in-depth for evidence excerpts (#769 Stage-2 P1 #2):
# reuse the SAME sanitizer the write path already applies, via the
# established cross-module import helper, rather than
# re-deriving the injection patterns here. See finalize_proposal() in
# lib/dream_analyze.py for the write-path sanitization this backstops.
sys.path.insert(0, os.path.join(os.environ["CCGM_DIGEST_MODULE_ROOT"], "lib"))
import transcript_miner as tm  # noqa: E402  (sibling module, same lib/ dir)

learnings_store = tm._import_sibling_module(  # noqa: SLF001
    "self-improving", "learnings_store", "sanitize_content for render-time excerpt neutralization"
)

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
canary = load_json(
    os.environ["CCGM_DIGEST_CANARY_FILE"],
    {"active_incidents": {}, "reduce_failures": {}},
)

# --- Composite-eligibility audit index (composite-eligibility plan.md §3.7,
# Epic E6). The optimistic-integrate engine writes ONE audit record per SCORED
# learning_add / learning_supersede row (audit_kind == "eligibility") into
# apply-audit.jsonl, carrying the full per-signal breakdown -- for eligible
# AND skipped rows. Index them by proposal_id so the Proposals section below
# can show WHY each scored row was admitted or held back, rejections
# (skipped_composite / skipped_origin / skipped_floor) especially
# (decisions.md #28). Last write wins -- a proposal is scored at most once per
# batch, so in practice there is exactly one record per proposal_id.
#
# This surface carries NO excerpt / transcript text: the eligibility record
# holds only the score, threshold, margin, the four normalized signals,
# session COUNTS and session ids, the evidence tier + its (id/line/origin)
# source, and unresolved session ids (§3.7 audit contract). It is therefore
# safe to render verbatim without the render_evidence() sanitizer pass.
eligibility_by_proposal = {}
for _rec in load_jsonl(os.environ.get("CCGM_DIGEST_APPLY_AUDIT_FILE", "")):
    if _rec.get("audit_kind") == "eligibility" and _rec.get("proposal_id"):
        eligibility_by_proposal[_rec["proposal_id"]] = _rec

out = []
out.append(f"# Dreaming digest — {target_date}")
out.append("")

# --- Durable canary banner (adrev-014 + #753 handoff) ----------------------
active_incidents = canary.get("active_incidents") or {}
# Reduce-phase failures (#769 Stage-2 P1 #1): main() aborts without
# writing proposals or advancing watermarks when the reduce call never
# returns a usable proposal array. That abort is
# otherwise only a stderr line an unattended launchd job will not
# surface -- record_reduce_failure_incident() writes it into this SAME
# durable file so it gets the same loud, persists-until-acknowledged
# banner as a schema_canary incident.
reduce_failures = canary.get("reduce_failures") or {}
if active_incidents or reduce_failures:
    out.append("## ⚠️ Canary banner (durable — shown until acknowledged)")
    out.append("")
    if active_incidents:
        out.append("**schema_canary fired for:**")
        out.append("")
        for slug, info in sorted(active_incidents.items()):
            out.append(f"- `{slug}` (first seen {info.get('date', '?')}): {info.get('detail', '')}")
        out.append("")
    if reduce_failures:
        out.append("**Reduce-phase failures (mined evidence NOT consumed, watermark NOT advanced):**")
        out.append("")
        for slug, info in sorted(reduce_failures.items()):
            out.append(f"- `{slug}` (last failed {info.get('date', '?')}): {info.get('detail', '')}")
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
    # #1026: a call that stopped at the output cap is a failed extraction,
    # not a short answer. Surfaced here so an unattended run's truncations
    # are visible in the same place as its call counts.
    truncated_calls = run_summary.get("truncated_calls", 0)
    if truncated_calls:
        out.append(
            f"- **calls that stopped at the output cap: {truncated_calls}** "
            "(failed extractions -- raise `max_output_tokens` if this repeats)"
        )
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

# --- Applied this run (auto) -- optimistic-memory plan.md Section 5 Epic 5.
#
# The Epic 3 optimistic-integration engine writes status: "auto_applied" +
# batch_id + posture + (for dwell postures) dwell_until directly onto a
# proposal row (apply_proposal() in apply_dream_proposal.py). The nightly
# chain runs optimistic-integrate BEFORE this digest (dream-daily.sh), so
# the proposals file for TODAY always carries the batch this section
# reports, with its dwell window still entirely ahead of it.
#
# "Already surfaced" dedup (plan.md: "the report shows a batch once, in
# the report for its own day"): a marker file per batch_id
# (state/surfaced/<batch_id>.json) is checked before rendering and written
# after. This is the ONLY dedup mechanism -- there is no separate
# same-day-vs-later-day special case: re-rendering the digest for the SAME
# day a second time (nothing new happened) and a batch_id that (defensively)
# resurfaces in the file for a LATER day are handled identically -- once a batch
# has been shown, it is never shown again.
#
# Silent when nothing (new) was auto-applied (research: a digest that
# fires on empty nights trains the reader to ignore it) -- the `if
# applied_rows:` guard below means no heading is emitted at all in that case.

ANOMALY_OUTCOMES = {"batch_anomaly_eviction_concentration", "rolling_add_rate_exceeded"}
BREAKER_TRIP_OUTCOME = "circuit_breaker_tripped"

surfaced_dir_env = os.environ.get("CCGM_DIGEST_SURFACED_DIR")
surfaced_dir = Path(surfaced_dir_env) if surfaced_dir_env else None


def already_surfaced(batch_id):
    if surfaced_dir is None or not batch_id:
        return False
    return (surfaced_dir / f"{batch_id}.json").is_file()


def mark_surfaced(batch_id, row_count):
    if surfaced_dir is None or not batch_id:
        return
    marker = surfaced_dir / f"{batch_id}.json"
    if marker.is_file():
        return
    surfaced_dir.mkdir(parents=True, exist_ok=True)
    marker.write_text(json.dumps({
        "batch_id": batch_id,
        "surfaced_at": _dt.datetime.now(_dt.timezone.utc).isoformat(),
        "date": target_date,
        "row_count": row_count,
    }, sort_keys=True), encoding="utf-8")


applied_all = [p for p in proposals if p.get("status") == "auto_applied" and p.get("batch_id")]
new_batch_ids = sorted({p["batch_id"] for p in applied_all if not already_surfaced(p["batch_id"])})
applied_rows = [p for p in applied_all if p.get("batch_id") in new_batch_ids]

if applied_rows:
    audit_records = load_jsonl(os.environ.get("CCGM_DIGEST_APPLY_AUDIT_FILE", ""))
    # Last write wins -- apply-audit.jsonl is append-only/chronological and
    # (per the adrev-013 "refuse non-pending" rule in apply_proposal()) a given
    # proposal_id is applied at most once, so in practice there is exactly
    # one matching record; this is a defensive tie-break, not a correctness
    # requirement.
    audit_by_proposal = {}
    for rec in audit_records:
        pid = rec.get("proposal_id")
        if pid:
            audit_by_proposal[pid] = rec

    def resolve_new_entry_id(proposal_id):
        rec = audit_by_proposal.get(proposal_id)
        return rec.get("new_entry_id") if rec else None

    def current_sha(project, entry_id):
        if not entry_id:
            return None
        try:
            heads = {h["id"]: h for h in learnings_store.load_all(project)}
        except Exception:
            return None
        head = heads.get(entry_id)
        if head is None:
            return None
        return learnings_store.content_sha256(head.get("content"))

    def row_target_id(p):
        # The learnings-store id "its" undo command below actually names --
        # for add/supersede this is the NEW entry the proposal created
        # (never recorded on the proposal row itself, only in the audit
        # trail); for contradict/deprecate it is the target_id already on that row.
        if p.get("kind") in ("learning_add", "learning_supersede"):
            return resolve_new_entry_id(p.get("id"))
        return p.get("target_id")

    def undo_command(p):
        kind = p.get("kind")
        project = p.get("project", "")
        if kind in ("learning_add", "learning_supersede"):
            entry_id = resolve_new_entry_id(p.get("id"))
            if not entry_id:
                return (f"(undo unavailable -- no `new_entry_id` recorded in apply-audit.jsonl "
                        f"for proposal `{p.get('id')}`; inspect the store manually)")
            sha = current_sha(project, entry_id)
            if not sha:
                return (f"`ccgm-learnings-log deprecate {entry_id} --project {project}` "
                        "(could not auto-resolve --expected-sha -- confirm the current sha with "
                        "`ccgm-learnings-search` before running)")
            return f"`ccgm-learnings-log deprecate {entry_id} --project {project} --expected-sha {sha}`"
        if kind in ("learning_contradict", "learning_deprecate"):
            target_id = p.get("target_id")
            if not target_id:
                return "(undo unavailable -- proposal carries no target_id)"
            return f"`ccgm-learnings-log verify {target_id} --project {project}`"
        return "(no reverse-op for this kind -- verify only reinforces usage; no undo needed)"

    mid_dwell = [p for p in applied_rows if learnings_store.is_dwelling(p)]
    live = [p for p in applied_rows if not learnings_store.is_dwelling(p)]

    anomaly_hits = [
        rec for rec in audit_records
        if rec.get("batch_id") in new_batch_ids and rec.get("outcome") in ANOMALY_OUTCOMES
    ]
    tripped_batches = sorted({
        rec.get("batch_id") for rec in audit_records
        if rec.get("batch_id") in new_batch_ids and rec.get("outcome") == BREAKER_TRIP_OUTCOME
    })
    flagged_count = len(anomaly_hits) + len(tripped_batches)

    def group_applied(rows):
        grouped = {}
        for p in rows:
            key = (p.get("project", "(unknown)"), p.get("kind", "(no-kind)"))
            grouped.setdefault(key, []).append(p)
        return grouped

    def render_applied_rows(rows):
        lines = []
        grouped = group_applied(rows)
        for project, kind in sorted(grouped):
            lines.append(f"#### {project} — {kind}")
            lines.append("")
            for p in sorted(grouped[(project, kind)], key=lambda p: p.get("id", "")):
                lines.append(f'##### `{p.get("id")}`')
                lines.append("")
                lines.append(f"- **target**: `{row_target_id(p) or '(unknown)'}`")
                lines.append(f"- **posture**: {p.get('posture', '?')}")
                if p.get("dwell_until"):
                    lines.append(f"- **dwell_until**: {p['dwell_until']}")
                lines.append(f"- **Undo**: {undo_command(p)}")
                lines.append("")
        return lines

    out.append("## Applied this run (auto)")
    out.append("")
    out.append(f"**{len(applied_rows)} auto-integrated, {len(mid_dwell)} mid-dwell, {flagged_count} flagged**")
    out.append("")

    if mid_dwell or anomaly_hits or tripped_batches:
        out.append("### Action items")
        out.append("")
        for batch_id in tripped_batches:
            out.append(f"- ⚠️ **circuit breaker tripped** during batch `{batch_id}` -- optimistic "
                       "auto-integration is now suspended; see `/dream` status.")
        for rec in anomaly_hits:
            out.append(f"- ⚠️ **{rec.get('outcome')}** on `{rec.get('project', '?')}` "
                       f"(batch `{rec.get('batch_id')}`) -- eviction proposals for this project were "
                       "skipped this run and remain `pending` for manual review.")
        if tripped_batches or anomaly_hits:
            out.append("")
        out.extend(render_applied_rows(mid_dwell))

    if live:
        out.append("### Routine confirmations")
        out.append("")
        out.extend(render_applied_rows(live))

    # Batch-revert (blunt option): resolvable via the commit message
    # run_optimistic_integrate() tags with the batch_id (adrev-opt-013 --
    # the engine guarantees exactly ONE commit per batch via its own
    # _suppressed_autocommit(), so no autocommit-detection is needed here;
    # the per-row Undo commands above remain the PREFERRED, single-row
    # rollback regardless of the ambient CCGM_LEARNINGS_AUTOCOMMIT setting).
    for batch_id in new_batch_ids:
        sha = None
        try:
            proc = subprocess.run(
                ["git", "-C", str(learnings_store.LEARNINGS_ROOT), "log",
                 f"--grep=batch {batch_id} ", "--format=%H", "-n", "1"],
                capture_output=True, text=True, timeout=5, check=False,
            )
            if proc.returncode == 0 and proc.stdout.strip():
                sha = proc.stdout.strip().splitlines()[0]
        except (OSError, subprocess.SubprocessError):
            sha = None
        if sha:
            out.append(
                f"- **Batch `{batch_id}` revert (blunt -- reverts EVERY row in this batch; prefer "
                f"the per-row Undo commands above)**: `git -C {learnings_store.LEARNINGS_ROOT} revert {sha}`"
            )
        else:
            out.append(
                f"- **Batch `{batch_id}` revert (blunt)**: commit not auto-resolved -- find it with "
                f"`git -C {learnings_store.LEARNINGS_ROOT} log --grep=\"batch {batch_id}\"`"
            )
    out.append("")

    for batch_id in new_batch_ids:
        mark_surfaced(batch_id, sum(1 for p in applied_rows if p.get("batch_id") == batch_id))


def render_evidence(evidence):
    lines = []
    for e in (evidence or [])[:3]:
        sid = e.get("session_id") or "(unknown session)"
        excerpt = e.get("excerpt") or ""
        # Render-time defense-in-depth (#769 Stage-2 P1 #2): the excerpt
        # was already sanitized at the proposal write path
        # (finalize_proposal), but this renderer must not assume every row
        # on disk went through that path -- neutralize again here so a
        # stale/hand-edited/pre-fix proposals file can never surface a
        # live injection pattern in the one artifact a human (or a
        # summarizing agent) actually reads.
        if excerpt:
            excerpt = learnings_store.sanitize_content(excerpt)
        lines.append(f"  - `{sid}`: {excerpt}")
    return lines


def _fmt_margin(margin):
    # margin = S - θ. Positive => admitted with headroom ("over"); negative =>
    # held back short of the bar ("short", by θ - S). Mirrors the plan.md §3.7
    # digest example: "S=0.541 (θ=0.58, short 0.039; weakest: novelty)".
    if margin is None:
        return None
    if margin >= 0:
        return f"over {margin:.3f}"
    return f"short {-margin:.3f}"


def render_eligibility(rec):
    """Render the §3.7 "Composite eligibility" subsection for one scored
    (learning_add / learning_supersede) proposal, from its eligibility audit
    record. Shown for eligible AND skipped rows. Renders only scalar
    signal/session data -- never excerpt or transcript text.

    Malformed-record tolerance (Stage-2 review fix): this heredoc renders the
    WHOLE day's digest -- including the durable canary banner -- so one audit
    record whose fields break the §3.7 shape (e.g. a non-numeric `score`
    hitting the `:.3f` format) must never raise and take the entire digest
    down. Same per-record discipline load_jsonl() applies per line
    (JSONDecodeError -> skip), applied at the render layer: the bad record
    renders as a one-line inline note pointing at the audit file, everything
    else renders normally."""
    if not rec:
        return []
    try:
        return _render_eligibility_lines(rec)
    except Exception:  # noqa: BLE001 -- render-layer tolerance, never fail the digest
        return ["- **Composite eligibility**: ⚠️ 1 eligibility record unrenderable — see audit file"]


def _render_eligibility_lines(rec):
    outcome = rec.get("outcome", "?")
    basis = rec.get("decision_basis")
    score = rec.get("score")
    threshold = rec.get("threshold")
    margin = rec.get("margin")
    weakest = rec.get("weakest_signal")
    signals = rec.get("signals") or {}

    lines = ["- **Composite eligibility**:"]
    head = f"  - `{outcome}`"
    if basis:
        head += f" (basis: {basis})"
    if score is not None and threshold is not None:
        # Composite ran (eligible via composite, or skipped_composite).
        head += f" — S={score:.3f} (θ={threshold}"
        margin_str = _fmt_margin(margin)
        if margin_str:
            head += f", {margin_str}"
        if weakest:
            head += f"; weakest: {weakest}"
        head += ")"
    else:
        # No composite score: skipped_floor, skipped_origin, or the legacy-floor
        # escape (decision_basis="legacy_floor") -- all admit/reject before S.
        head += f" — score not computed (θ={threshold})"
    lines.append(head)

    if signals:
        sig_str = ", ".join(
            f"{name}={signals[name]:.2f}"
            for name in ("confidence", "prevalence", "recency", "novelty")
            if name in signals
        )
        lines.append(f"  - signals: {sig_str}")

    tier_line = f"  - evidence tier: {rec.get('evidence_tier', '?')}"
    src = rec.get("evidence_tier_source")
    if isinstance(src, dict):
        # {session_id, line, origin_kind} -- ids/line-number/origin only, no text.
        tier_line += f" (from `{src.get('session_id', '?')}`"
        if src.get("line") is not None:
            tier_line += f" line {src.get('line')}"
        if src.get("origin_kind"):
            tier_line += f", origin={src.get('origin_kind')}"
        tier_line += ")"
    lines.append(tier_line)

    unresolved = rec.get("unresolved_session_ids") or []
    lines.append(f"  - verified sessions: {rec.get('verified_sessions', '?')}; "
                 f"unresolved: {len(unresolved)}")
    if rec.get("near_duplicate_supersede"):
        lines.append("  - ⚠️ near-duplicate supersede with changed facts — review")
    return lines


def render_proposal(p):
    pid = p.get("id", "(no-id)")
    confidence = p.get("confidence", "?")
    prevalence = p.get("prevalence") or {}
    lines = [
        f"##### `{pid}`",
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
    # Composite-eligibility breakdown (composite-eligibility plan.md §3.7, E6):
    # present only for scored add/supersede rows when the optimistic engine ran
    # (an eligibility audit record exists for this proposal_id). Absent for
    # legacy/disabled-mode nights, non-scored kinds, and gated rows.
    lines.extend(render_eligibility(eligibility_by_proposal.get(pid)))
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

    # Grouped by project, then by kind (#769 Stage-1 concern 2: plan.md
    # §5 Epic 3 specifies "proposals grouped by project/kind" -- kind was
    # previously shown per-card only, not as its own grouping dimension).
    grouped = {}
    for p in proposals:
        key = (p.get("project", "(unknown)"), p.get("kind", "(no-kind)"))
        grouped.setdefault(key, []).append(p)

    projects = sorted({proj for proj, _kind in grouped})
    for project in projects:
        out.append(f"### {project}")
        out.append("")
        kinds = sorted({k for (proj, k) in grouped if proj == project})
        for kind in kinds:
            out.append(f"#### {kind}")
            out.append("")
            rows = sorted(grouped[(project, kind)], key=lambda p: (-(int(p.get("confidence") or 0)), p.get("id", "")))
            for p in rows:
                out.append(render_proposal(p))

# --- Prior-day applied/rejected tally ------------------------------------
out.append("## Prior-day tally")
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
